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
            r = requests.get('https://api.github.com/repos/Voxel8/Marlin/releases/latest')
            rjson = r.json()
            self.firmware_directory = os.path.join(os.path.expanduser('~'), 'Marlin/.build/mega2560/')
            if not os.path.exists(self.firmware_directory):
                os.makedirs(self.firmware_directory)
            self.firmware_file = os.path.join(self.firmware_directory, 'Marlin/.build/mega2560/firmware.hex')
            urllib.urlretrieve(rjson['assets'][0]['browser_download_url'], self.firmware_file)
            if os.path.isfile(self.firmware_file):
                self.isUpdating = True
                self._logger.info("File downloaded, continuing...")
                self._update_firmware("github")
            else:
                self.isUpdating = False
                self._logger.info("Failed update... Release firmware was not downloaded")

    def _update_firmware(self, target):
        if not self.isUpdating:
            # TODO: Update this error message to be more helpful
            self._logger.info("Something doesn't make sense here...")
        else:
            self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, createPopup="yes"))
            self._update_firmware_thread = Thread(target=self._update_worker)
            self._update_firmware_thread.daemon = True
            self._update_firmware_thread.start()

    def _update_worker(self):
        self._logger.info("Updating now...")
        pipe = Popen("cd ~/Marlin/; avrdude -p m2560 -P /dev/ttyACM0 -c stk500v2 -b 250000 -D -U flash:w:./.build/mega2560/firmware.hex:i", shell=True, stdout=PIPE, stderr=PIPE)
        results = pipe.communicate()
        stdout = results[0]
        stderr = results[1]
        self._logger.info(stdout)
        self._logger.info(stderr)

        if 'bytes of flash verified' in stdout and 'successfully' in stdout:
            self._logger.info("Successful update!")
            self.isUpdating = False
    	    self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="completed"))
        elif 'Permission denied' in stderr:
            self._logger.info("Permission denied. No port available.")
            self.isUpdating = False
    	    self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="failed", reason="A connected device was not found."))
        elif 'No device matching following was found' in stderr:
    	    self._logger.info("Failed update...")
            self.isUpdating = False
    	    self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="failed", reason="A connected device was not found."))
    	elif 'FAILED' in stderr:
    	    self._logger.info("Failed update...")
            self.isUpdating = False
    	    self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="failed"))
        elif 'ReceiveMessage(): timeout' in stderr:
    	    self._logger.info("Update timed out. Check if port is already in use!")
    	    self.isUpdating = False
    	    self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="failed", reason="Device timed out. Please check that the port is not in use!"))
        else:
            self.isUpdating = False
    	    self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="failed", reason="Unknown error occurred."))
        # Clean up firmware files
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
