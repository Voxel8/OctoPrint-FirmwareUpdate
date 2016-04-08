# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
import flask
import os
from subprocess import Popen
import psutil
from time import sleep
import requests
import urllib
from threading import Thread
from glob import glob
from serial import Serial, SerialException
from octoprint.events import eventManager, Events

Events.FIRMWARE_UPDATE = "FirmwareUpdate"

__author__ = "Kevin Murphy <kevin@voxel8.co>"
__license__ = "GNU Affero General Public License http://www.gnu.org/licenses/agpl.html"
__copyright__ = "Copyright (C) 2015 Kevin Murphy - Released under terms of the AGPLv3 License"


class FirmwareUpdatePlugin(octoprint.plugin.StartupPlugin,
                           octoprint.plugin.TemplatePlugin,
                           octoprint.plugin.AssetPlugin,
                           octoprint.plugin.SettingsPlugin,
                           octoprint.plugin.SimpleApiPlugin):

    def __init__(self):
        self.isUpdating = False
        self.firmware_file = None
        self.version_file = None
        self._checkTimer = None
        self.updatePID = None
        self.f = None
        self.completion_time = 0
        self.write_time = None
        self.read_time = None
        self.port = None
        self.version = None

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
            self._start_update()

        else:
            self._logger.info("Uknown command.")

    def on_api_get(self, request):
        return flask.jsonify(isUpdating=self.isUpdating)

    def on_after_startup(self):
        self._start_update(True)

    def _start_update(self, onstartup=False):
        self._update_firmware_init_thread = Thread(target=self._update_firmware_init, args=(onstartup,))
        self._update_firmware_init_thread.daemon = True
        self._update_firmware_init_thread.start()

    def checkStatus(self):
        while True:
            update_result = open(os.path.join(os.path.expanduser('~'), 'Marlin/.build_log')).read()
            if 'No device matching following was found' in update_result:
                self._logger.info("Failed update...")
                self._update_status(False, "error", "A connected device was not found.")
                self._clean_up()
                break
            elif 'FAILED' in update_result:
                self._logger.info("Failed update...")
                self._update_status(False, "error")
                self._clean_up()
                break
            elif 'bytes of flash verified' in update_result and 'avrdude done' in update_result:
                self._logger.info("Successful update!")
                for line in update_result.splitlines():
                    if "Reading" in line:
                        self.read_time = self.find_between(line, " ", "s")
                        self.completion_time += float(self.read_time)
                    elif "Writing" in line:
                        self.write_time = self.find_between(line, " ", "s")
                        self.completion_time += float(self.write_time)

                self._update_status(False, "completed", round(self.completion_time, 2))
                self._clean_up()
                break
            elif 'ReceiveMessage(): timeout' in update_result:
                self._logger.info("Update timed out. Check if port is already in use!")
                self._update_status(False, "error", "Device timed out. Please check that the port is not in use!")

                p = psutil.Process(self.updatePID)
                for child in p.children(recursive=True):
                    child.kill()
                    p.kill()
                self._clean_up()
                break
            sleep(1)

    def _update_firmware_init(self, onstartup=False):
        if self.printer_is_printing():
            self._update_status(False, "error", "Printer is in use.")
            raise RuntimeError("Printer is in use - cannot continue")

        self.firmware_directory = os.path.join(os.path.expanduser('~'), 'Marlin/.build/mega2560/')
        self.src_directory = os.path.join(os.path.expanduser('~'), 'Marlin/src')
        self.version_file = os.path.join(os.path.expanduser('~'), 'Marlin/.version')
        if not os.path.exists(self.firmware_directory):
            os.makedirs(self.firmware_directory)
        if not os.path.exists(self.src_directory):
            os.makedirs(self.src_directory)

        if onstartup:
            # Delete all files inside firmware_directory
            filelist = glob(self.firmware_directory + "*.hex")
            for f in filelist:
                os.remove(f)
            # Check against current version
            if not os.path.isfile(self.version_file):
                self._logger.info("No version file exists, grabbing latest from GitHub")
                self._update_status(True, "inprogress")

                self._update_from_github()
            else:
                with open(self.version_file, 'r') as f:
                    self.version = f.readline()

                r = requests.get('https://api.github.com/repos/Voxel8/Marlin/releases/latest')
                rjson = r.json()
                github_version = rjson['assets'][0]['updated_at']

                if self.version == github_version:
                    # Skip Update TODO
                    self._logger.info("Skipping update process")
                    self.isUpdating = False
                else:
                    self._logger.info("Version in file is different, grabbing from GitHub")
                    self._update_status(True, "inprogress")

                    self._update_from_github()
        else:
            filenames = os.listdir(self.firmware_directory)
            if len(filenames) > 0:
                if filenames[0].endswith('.hex'):
                    file_exists = True
                else:
                    file_exists = False
            else:
                file_exists = False

            if file_exists:
                self._logger.info("Updating using " + filenames[0])
                self._update_status(True, "inprogress")

                self.firmware_file = os.path.join(os.path.expanduser('~'), 'Marlin/.build/mega2560/' + filenames[0])
                self._update_firmware("local")
            else:
                self._logger.info("No files exist, grabbing latest from GitHub")
                self._update_status(True, "inprogress")

                self._update_from_github()

    def _update_from_github(self):
        r = requests.get('https://api.github.com/repos/Voxel8/Marlin/releases/latest')
        rjson = r.json()
        self.firmware_file = os.path.join(self.firmware_directory, 'firmware.hex')
        # Write version to File
        with open(self.version_file, 'w') as f:
            f.write(rjson['assets'][0]['updated_at'])
        urllib.urlretrieve(rjson['assets'][0]['browser_download_url'], self.firmware_file)
        if os.path.isfile(self.firmware_file):
            self._logger.info("File downloaded, continuing...")
            self._update_firmware("github")
        else:
            self._update_status(False, "error", "Release firmware was not downloaded.")

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
            self.port = glob('/dev/ttyACM*')[0]
        except IndexError:
            self._update_status(False, "error", "No ports exist.")
            raise RuntimeError('No ports detected')

        try:
            os.remove(os.path.join(os.path.expanduser('~'), 'Marlin/.build_log'))
        except OSError:
            self._logger.info("Couldn't delete build log file")
        self.f = open(os.path.join(os.path.expanduser('~'), 'Marlin/.build_log'), "w")
        try:
            s = Serial(self.port, 115200)
        except SerialException as e:
            self._update_status(False, "error", str(e))
            raise RuntimeError(str(e))
        s.setDTR(False)
        sleep(0.1)
        s.setDTR(True)
        s.close()
        pro = Popen("cd ~/Marlin/; avrdude -p m2560 -P /dev/ttyACM0 -c stk500v2 -b 250000 -D -U flash:w:./.build/mega2560/firmware.hex:i", stdout=self.f, stderr=self.f, shell=True, preexec_fn=os.setsid)
        self.updatePID = pro.pid
        self.checkStatus()

    def find_between(self, s, first, last):
        try:
            start = s.rindex(first) + len(first)
            end = s.rindex(last, start)
            return s[start:end]
        except ValueError:
            return ""

    def _update_status(self, isUpdating, status=None, message=None):
        self.isUpdating = isUpdating
        # Reconnect again after no longer updating
        if not self.isUpdating:
            self._printer.connect()
            if status == "error":
                os.remove(self.version_file)
        else:
            self._printer.disconnect()

        self._plugin_manager.send_plugin_message(self._identifier, dict(isUpdating=self.isUpdating, status=status, message=message))
        payload = {'isUpdating': self.isUpdating, 'status': status, 'message': message}
        eventManager().fire(Events.FIRMWARE_UPDATE, payload)

    def _clean_up(self):
        if self.f is not None:
            if not self.f.closed:
                self.f.close()
        try:
            os.remove(os.remove(os.path.join(os.path.expanduser('~'), 'Marlin/.build_log')))
        except OSError:
            pass
        os.remove(self.firmware_file)

    def printer_is_printing(self):
        if self._printer.is_printing() or self._printer.is_paused():
            return True
        return False

    def _get_firmware_date(self):
        return 1

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
