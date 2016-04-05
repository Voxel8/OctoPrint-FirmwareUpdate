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
        self._checkTimer = None
        self.updatePID = None

    def get_assets(self):
        return {
            "js": ["js/firmwareupdate.js"]
        }

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

    def get_api_commands(self):
        return dict(
            update_firmware=[],
	        check_is_updating=[]
        )

    def on_api_command(self, command, data):
    	if command == "update_firmware":
            self._update_firmware_init_thread = Thread(target=self._update_firmware_init)
            self._update_firmware_init_thread.daemon = True
            self._update_firmware_init_thread.start()

    	elif command == "check_is_updating":
    	    if self.isUpdating == True:
    	        self._logger.info("Setting isUpdating to " + str(self.isUpdating))
    	        self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, createPopup="yes"))
    	    else:
    	        self._logger.info("Setting isUpdating to " + str(self.isUpdating))
    	        self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, deletePopup="yes"))
    	else:
    	    self._logger.info("Uknown command.")

    def on_api_get(self, request):
        return flask.make_response("Not found", 404)

    def _update_firmware_init(self):
        marlin_dir = os.path.join(os.path.expanduser('~'), 'Marlin/.build/')
        filenames = os.listdir(marlin_dir)
        if len(filenames) > 0:
            if filenames[0].endswith('.hex'):
                file_exists = True
            else:
                file_exists = False
        if file_exists:
            self.isUpdating = True
            self._logger.info("Updating using " + filenames[0])
            self._update_firmware("local")
        else:
            self._logger.info("No files exist, grabbing latest from GitHub")
            r = requests.get('https://api.github.com/repos/Voxel8/Marlin/releases/latest')
            rjson = r.json()
            firmware_file = os.path.join(os.path.expanduser('~'), 'Marlin/.build/firmware.hex')
            urllib.urlretrieve(rjson['assets'][0]['browser_download_url'], firmware_file)
            if os.path.isfile(firmware_file):
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
            self._update_firmware_thread = Thread(target=self._update_worker)
            self._update_firmware_thread.daemon = True
            self._update_firmware_thread.start()

    def _update_worker(self):
        self._logger.info("Updating now...")
        pipe = Popen("cd ~/Marlin/; ino upload -m mega2560", shell=True, stdout=PIPE, stderr=PIPE)
        results = pipe.communicate()
        self._logger.info(results[0])
        self._logger.info(results[1])

    def get_template_configs(self):
        return [
            dict(type="settings", name="Firmware Update", data_bind="visible: loginState.isAdmin()"),
	    ]

__plugin_name__ = "Firmware Update Plugin"

def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = FirmwareUpdatePlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
	}
