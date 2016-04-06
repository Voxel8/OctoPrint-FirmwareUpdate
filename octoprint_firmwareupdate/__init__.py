# coding=utf-8
from __future__ import absolute_import

__author__ = "Kevin Murphy <kevin@voxel8.co>"
__license__ = "GNU Affero General Public License http://www.gnu.org/licenses/agpl.html"
__copyright__ = "Copyright (C) 2015 Kevin Murphy - Released under terms of the AGPLv3 License"

import octoprint.plugin
from octoprint.util import RepeatedTimer
import flask
import os
from subprocess import Popen, PIPE
import signal
import linecache
import psutil
import time
import requests
import json
import urllib
from threading import Thread

class FirmwareUpdatePlugin(octoprint.plugin.StartupPlugin,
                       octoprint.plugin.TemplatePlugin,
                       octoprint.plugin.AssetPlugin,
                       octoprint.plugin.SettingsPlugin,
                       octoprint.plugin.SimpleApiPlugin):

    def __init__(self):
        self.isUpdating = False
        self.firmware_file = None
        self._checkTimer = None
        self.updatePID = None
        self.f = None
        self.completion_time = None

    def get_assets(self):
        return {
            "js": ["js/firmwareupdate.js"]
        }

    def get_api_commands(self):
        return dict(
            update_firmware=[]
        )

    def on_api_command(self, command, data):
    	if command == "update_firmware":
            self._update_firmware_init_thread = Thread(target=self._update_firmware_init)
            self._update_firmware_init_thread.daemon = True
            self._update_firmware_init_thread.start()

    	else:
    	    self._logger.info("Uknown command.")

    def on_api_get(self, request):
        return flask.jsonify(status=self.isUpdating)

    def startTimer(self, interval):
        self._checkTimer = RepeatedTimer(interval, self.checkStatus, run_first=True, condition=self.checkStatus)
        self._checkTimer.start()

    def checkStatus(self):
        update_result = open('/home/pi/Marlin/.build_log').read()
        if 'No device matching following was found' in update_result:
    	    self._logger.info("Failed update...")
            self.isUpdating = False
    	    self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="failed", reason="A connected device was not found."))
            self._clean_up()
    	    return False
    	elif 'FAILED' in update_result:
    	    self._logger.info("Failed update...")
            self.isUpdating = False
    	    self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="failed"))
            self._clean_up()
    	    return False
    	elif 'bytes of flash verified' in update_result and 'successfully' in update_result :
            self._logger.info("Successful update!")
    	    self.isUpdating = False
            for line in update_result:
                if "Reading" in line:
                    self.completion_time = find_between( line, " ", "s" )
    	    self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="completed"), completion_time=self.completion_time)
            self._clean_up()
    	    return False
    	elif 'ReceiveMessage(): timeout' in update_result:
    	    self._logger.info("Update timed out. Check if port is already in use!")
    	    self.isUpdating = False
    	    self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="failed", reason="Device timed out. Please check that the port is not in use!"))
    	    p = psutil.Process(self.updatePID)
    	    for child in p.children(recursive=True):
        	    child.kill()
    	    p.kill()
            self._clean_up()
    	    return False
    	elif 'error:' in update_result:
    	    error_list = []
            with open('/home/pi/Marlin/.build_log') as myFile:
    		for num, line in enumerate(myFile, 1):
    		    if 'error:' in line:
    			    error_list.append(line)
    	    compileError = '<pre>' + ''.join(error_list) + '</pre>'
    	    self._logger.info("Update failed. Compiling error.")
    	    self.isUpdating = False
    	    self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="failed", reason=compileError))
    	    self._clean_up()
            return False
    	elif 'Make failed' in update_result:
    	    self._logger.info("Update failed. Compiling error.")
    	    self.isUpdating = False
    	    self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="failed", reason="Build failed."))
    	    self._clean_up()
            return False
    	else:
    	    self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="continue"))
    	    return True

    def _update_firmware_init(self):
        marlin_dir = os.path.join(os.path.expanduser('~'), 'Marlin/.build/')
        filenames = os.listdir(marlin_dir)
        if len(filenames) > 0:
            if filenames[0].endswith('.hex'):
                file_exists = True
            else:
                file_exists = False
        else :
            file_exists = False

        if file_exists:
            self.isUpdating = True
            self._logger.info("Updating using " + filenames[0])
            self.firmware_file = os.path.join(os.path.expanduser('~'), 'Marlin/.build/mega2560/' + filenames[0])
            self._update_firmware("local")
        else:
            self._logger.info("No files exist, grabbing latest from GitHub")
            self.isUpdating = True
            self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, createPopup="yes"))
            r = requests.get('https://api.github.com/repos/Voxel8/Marlin/releases/latest')
            rjson = r.json()
            self.firmware_directory = os.path.join(os.path.expanduser('~'), 'Marlin/.build/mega2560/')
            if not os.path.exists(self.firmware_directory):
                os.makedirs(self.firmware_directory)
            self.firmware_file = os.path.join(self.firmware_directory, 'firmware.hex')
            urllib.urlretrieve(rjson['assets'][0]['browser_download_url'], self.firmware_file)
            if os.path.isfile(self.firmware_file):
                self._logger.info("File downloaded, continuing...")
                self._update_firmware("github")
            else:
                self.isUpdating = False
                self._logger.info("Failed update... Release firmware was not downloaded")
                self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="failed", reason="Release firmware was not downloaded."))

    def _update_firmware(self, target):
        if not self.isUpdating:
            # TODO: Update this error message to be more helpful
            self._logger.info("Something doesn't make sense here...")
        else:
            self._update_firmware_thread = Thread(target=self._update_worker)
            self._update_firmware_thread.daemon = True
            self._update_firmware_thread.start()

    def _update_worker(self):
        self._logger.info("Updating now...")
        try:
            os.remove(os.path.join(os.path.expanduser('~'), 'Marlin/.build_log'))
        except OSError:
            pass
        self.f = open("/home/pi/Marlin/.build_log", "w")
        pro = Popen("cd ~/Marlin/; avrdude -p m2560 -P /dev/ttyACM0 -c stk500v2 -b 250000 -D -U flash:w:./.build/mega2560/firmware.hex:i", stdout=self.f, stderr=self.f, shell=True, preexec_fn=os.setsid)
        self.updatePID = pro.pid
        self.startTimer(1.0)

    def find_between(self, s, first, last ):
        try:
            start = s.rindex( first ) + len( first )
            end = s.rindex( last, start )
            return s[start:end]
        except ValueError:
            return ""

    def _clean_up(self):
        if self.f is not None:
            if not self.f.closed:
                self.f.close()
        os.remove(self.firmware_file)

    def get_template_configs(self):
        return [
            dict(type="settings", name="Firmware Update", data_bind="visible: loginState.isAdmin()"),
	    ]

    def get_update_information(self):
        return dict(
            firmwareupdate_plugin=dict(
                displayName="FirmwareUpdate Plugin",
                displayVersion=self._plugin_version,
                type="github_commit",
                user="Voxel8",
                repo="OctoPrint-FirmwareUpdate",
                current=self._plugin_version,
                pip="https://github.com/Voxel8/OctoPrint-FirmwareUpdate/archive/{target_version}.zip"
            )
        )

__plugin_name__ = "Firmware Update Plugin"

def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = FirmwareUpdatePlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
	}
