$(function() {
  function FirmwareUpdateViewModel(parameters) {
    var self = this;

    self.printerState = parameters[0];
    self.loginState = parameters[1];
    self.connectionState = parameters[2];
    self.settings = parameters[3];
    self.popup = undefined;
    self.isUpdating = ko.observable(undefined);
    self.enableUpdating = ko.computed(function() {
      return self.isUpdating() == false ? true : false;
    });

    self._showPopup = function(options, eventListeners) {
      self._closePopup();
      self.popup = new PNotify(options);

      if (eventListeners) {
        var popupObj = self.popup.get();
        _.each(eventListeners, function(value, key) {
          popupObj.on(key, value);
        })
      }
    };

    self._updatePopup = function(options) {
      if (self.popup === undefined) {
        self._showPopup(options);
      } else {
        self.popup.update(options);
      }
    };

    self._closePopup = function() {
      if (self.popup !== undefined) {
        self.popup.remove();
      }
    };

    self.onDataUpdaterReconnect = function() {
      self.checkUpdating();
    }

    self.onStartupComplete = function() {
      self.checkUpdating();
    }

    self.onDataUpdaterPluginMessage = function(plugin, data) {
      if (plugin != "firmwareupdate") {
        return;
      }
      if (data.hasOwnProperty("isUpdating")) {
        self.isUpdating(data.isUpdating);
        if (data.status == "error") {
          if (data.message) {
            $("#printer_connect").prop("disabled", false);
            self._showPopup({
              title: gettext("Update failed!"),
              text: gettext("Updating your printer firmware was not successful.<br>" + pnotifyAdditionalInfo(data.message)),
              type: "error",
              hide: false,
              buttons: {
                sticker: false
              }
            });
          } else {
            $("#printer_connect").prop("disabled", false);
            self._showPopup({
              title: gettext("Update failed!"),
              text: gettext("Updating your printer firmware was not successful."),
              type: "error",
              hide: false,
              buttons: {
                sticker: false
              }
            });
          }
        } else if (data.status == "completed") {
          $("#printer_connect").prop("disabled", false);
          self._showPopup({
            title: gettext("Update complete."),
            text: gettext("The firmware on your printer has been successfully updated after " + data.message + " seconds."),
            type: "success",
            hide: false,
            buttons: {
              sticker: false
            }
          });
        } else if (data.status == "inprogress") {
          $("#printer_connect").prop("disabled", true);
          self._showPopup({
            title: gettext("Updating..."),
            text: gettext("Now updating, please wait."),
            icon: "icon-cog icon-spin",
            hide: false,
            buttons: {
              closer: false,
              sticker: false
            }
          });
        } else if (data.deletePopup == "yes") {
          self._closePopup();
        }
      }
    }

    self.update_firmware_enable = function() {
      self.isUpdating(false);
    }

    self.update_firmware = function() {
      $("#printer_connect").prop("disabled", true);
      $.ajax({
        type: "POST",
        url: "/api/plugin/firmwareupdate",
        data: JSON.stringify({
          command: 'update_firmware'
        }),
        contentType: "application/json; charset=utf-8",
        dataType: "json"
      });
    };

    self.checkUpdating = function() {
      $.ajax({
        type: "GET",
        url: "/api/plugin/firmwareupdate",
        contentType: "application/json; charset=utf-8",
        dataType: "json",
        error: function(jqXHR, exception) {
          console.log('error');
        },
        success: function(data) {
          self.isUpdating(data.isUpdating);
          if (data.isUpdating) {
            $("#printer_connect").prop("disabled", true);
            self._showPopup({
              title: gettext("Updating..."),
              text: gettext("Now updating, please wait."),
              icon: "icon-cog icon-spin",
              hide: false,
              buttons: {
                closer: false,
                sticker: false
              }
            });
          } else {
            self._closePopup();
          }
        }
      });
    };
  }

  ADDITIONAL_VIEWMODELS.push([
    FirmwareUpdateViewModel, ["printerStateViewModel", "loginStateViewModel", "connectionViewModel", "settingsViewModel"],
    ["#settings_plugin_firmwareupdate"]
  ]);
});
