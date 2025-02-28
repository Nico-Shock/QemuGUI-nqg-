#!/usr/bin/env python3
import os, json, subprocess, shutil, threading, urllib.parse

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib

#### CONFIGURATION ####
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".nqg")
if not os.path.exists(CONFIG_DIR):
    os.makedirs(CONFIG_DIR)
CONFIG_FILE = os.path.join(CONFIG_DIR, "vms_index.json")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

#### OVMF FILE HANDLING ####
# Copies firmware files only when switching to a UEFI mode.
def copy_uefi_files(config, parent_window=None):
    ovmf_dir = os.path.join(config["path"], "ovmf")
    os.makedirs(ovmf_dir, exist_ok=True)
    src_dir = "/usr/share/edk2/x64"
    # Choose files based on firmware selection.
    if config["firmware"] == "UEFI":
        files = ["OVMF.4m.fd", "OVMF_VARS.4m.fd"]
    elif config["firmware"] == "UEFI+Secure Boot":
        files = ["OVMF_CODE.4m.fd", "OVMF_VARS.4m.fd"]
    else:
        return True # Indicate success for BIOS case
    success = True
    copied_count = 0
    for f in files:
        src = os.path.join(src_dir, f)
        dst = os.path.join(ovmf_dir, f)
        if os.path.exists(src):
            try:
                shutil.copy(src, dst)
                copied_count += 1
            except Exception as e_base:
                sudo_pwd = prompt_sudo_password(parent_window)
                if sudo_pwd is not None:
                    full_cmd = f"echo {sudo_pwd} | sudo -S cp '{src}' '{dst}'"
                    try:
                        # Ausgabe nach /dev/null umleiten
                        subprocess.run(full_cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        copied_count += 1
                    except subprocess.CalledProcessError as e_sudo:
                        error_msg = str(e_sudo)
                        show_error_dialog(f"Fehler beim Kopieren der UEFI Firmware Dateien mit Sudo: {error_msg}\n\nÜberprüfen Sie Ihr Sudo-Passwort und die Berechtigungen.", parent_window)
                        return False
                    except Exception as e_sudo_other:
                        error_msg = str(e_sudo_other)
                        show_error_dialog(f"Unerwarteter Fehler beim Kopieren der UEFI Dateien mit Sudo: {error_msg}\n\nÜberprüfen Sie Ihre Sudo-Einrichtung und Berechtigungen.", parent_window)
                        return False
                else:
                    show_error_dialog("Sudo-Passwort benötigt, aber nicht eingegeben. Kopieren der UEFI-Dateien fehlgeschlagen.", parent_window)
                    return False
            except Exception as e_initial_other:
                error_msg = str(e_initial_other)
                show_error_dialog(f"Unerwarteter Fehler beim Kopieren der UEFI Dateien: {error_msg}\n\nÜberprüfen Sie die Dateiberechtigungen und Paketinstallation.", parent_window)
                return False

    if config["firmware"] == "UEFI":
        config["ovmf_bios"] = os.path.join(ovmf_dir, "OVMF.4m.fd")
    elif config["firmware"] == "UEFI+Secure Boot":
        config["ovmf_code_secure"] = os.path.join(ovmf_dir, "OVMF_CODE.4m.fd")
        config["ovmf_vars_secure"] = os.path.join(ovmf_dir, "OVMF_VARS.4m.fd")

    if copied_count == 0 and config["firmware"] in ["UEFI", "UEFI+Secure Boot"]:
        show_error_dialog(f"Keine UEFI Firmware Dateien in {src_dir} gefunden. \n\nStellen Sie sicher, dass das Paket `edk2-ovmf` installiert ist und die Dateien im erwarteten Verzeichnis vorhanden sind.", parent_window)
        return False

    return success

def delete_ovmf_dir(config):
    ovmf_dir = os.path.join(config["path"], "ovmf")
    if os.path.exists(ovmf_dir):
        try:
            shutil.rmtree(ovmf_dir)
        except Exception as e:
            show_error_dialog(f"Fehler beim Löschen des OVMF-Verzeichnisses: {e}", main_win) #Main win not defined here, use None or parent_window if passed down
            return False
    return True

#### LAUNCH CMD BUILDER ####
def build_launch_command(config):
    """Builds QEMU launch command."""
    qemu = shutil.which("qemu-kvm") or shutil.which("qemu-system-x86_64")
    if not qemu:
        show_error_dialog("QEMU Binärdatei nicht gefunden!", main_win)
        return None # Return None if QEMU not found
    cmd = [
        qemu, "-enable-kvm", "-cpu", "host",
        "-smp", str(config["cpu"]),
        "-m", str(config["ram"]),
        "-drive", f"file={config['disk_image']},format={config['disk_type']},if=virtio",
        "-boot", "order=dc,menu=off",
        "-usb", "-device", "usb-tablet",
        "-netdev", "user,id=net0", "-device", "virtio-net-pci,netdev=net0",
        "-vga", "virtio"
    ]
    disp = config["display"].lower()
    if disp == "gtk (default)":
        cmd.extend(["-display", "gtk,gl=on" if config.get("3d_acceleration", False) else "gtk"])
    elif disp == "virtio":
        cmd.extend(["-display", "virtio,gl=on" if config.get("3d_acceleration", False) else "virtio"])
    elif disp == "spice (virtio)":
        cmd.extend(["-display", "spice-app"])
    elif disp == "qemu":
        pass
    if config.get("iso_enabled") and config.get("iso"):
        iso_path = urllib.parse.unquote(config["iso"])
        cmd.extend(["-cdrom", iso_path])
    if config["firmware"] == "UEFI":
        if config.get("ovmf_bios"):
            cmd.extend(["-bios", config["ovmf_bios"]])
    elif config["firmware"] == "UEFI+Secure Boot":
        ovmf_code_secure = os.path.join(config["path"], "ovmf", "OVMF_CODE.4m.fd")
        ovmf_vars_secure = os.path.join(config["path"], "ovmf", "OVMF_VARS.4m.fd")
        if os.path.exists(ovmf_code_secure) and os.path.exists(ovmf_vars_secure):
            cmd.extend([
                "-drive", f"if=pflash,format=raw,readonly=on,file={ovmf_code_secure}",
                "-drive", f"if=pflash,format=raw,file={ovmf_vars_secure}"
            ])
        else:
            show_error_dialog("Sicherer Boot Firmware Dateien fehlen!", main_win) #Main win not defined here, should pass parent
    if config.get("tpm_enabled", False):
        tpm_dir = os.path.join(config["path"], "tpm")
        os.makedirs(tpm_dir, exist_ok=True)
        tpm_sock_path = os.path.join(tpm_dir, "tpm0.sock")
        if os.path.exists(tpm_sock_path):
            os.remove(tpm_sock_path)
        cmd.extend([
            "-chardev", f"socket,id=chrtpm,server=on,wait=off,path={tpm_sock_path}",
            "-tpmdev", f"emulator,id=tpm0,chardev=chrtpm",
            "-device", "tpm-crb,tpmdev=tpm0"
        ])
    return cmd

#### CONFIG LOAD/SAVE ####
def load_vm_index():
    """Loads VM index from config file."""
    if os.path.exists(CONFIG_FILE) and os.path.getsize(CONFIG_FILE) > 0:
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_vm_index(index):
    """Saves VM index to config file."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(index, f, indent=4)

def load_all_vm_configs():
    """Loads all VM configurations."""
    index = load_vm_index()
    configs = []
    for vm_path in index:
        try:
            for fname in os.listdir(vm_path):
                if fname.endswith(".json"):
                    with open(os.path.join(vm_path, fname), "r") as f:
                        configs.append(json.load(f))
                    break
        except Exception as e:
            show_error_dialog(f"Fehler beim Laden der Konfiguration aus {vm_path}: {e}", main_win) #Main win not defined here, should pass parent
    return configs

def save_vm_config(config):
    """Saves VM configuration to file."""
    conf_file = os.path.join(config["path"], f"{config['name']}.json")
    try:
        with open(conf_file, "w") as f:
            json.dump(config, f, indent=4)
    except Exception:
        show_error_dialog("Fehler beim Speichern der VM-Konfiguration.\nÜberprüfen Sie Ihre Berechtigungen.", main_win)
        raise

#### SUDO PROMPT ####
def prompt_sudo_password(parent):
    """Prompts user for sudo password."""
    d = Gtk.Dialog(title="Sudo-Passwort benötigt", transient_for=parent, flags=0)
    d.add_buttons("OK", Gtk.ResponseType.OK, "Abbrechen", Gtk.ResponseType.CANCEL)
    box = d.get_content_area()
    box.add(Gtk.Label(label="Geben Sie Ihr Sudo-Passwort ein, um UEFI-Dateien zu installieren:"))
    entry = Gtk.Entry()
    entry.set_visibility(False)
    box.add(entry)
    d.show_all()
    resp = d.run()
    pwd = entry.get_text() if resp == Gtk.ResponseType.OK else None
    d.destroy()
    return pwd

#### LOADING DIALOG ####
class LoadingDialog(Gtk.Dialog):
    """Loading dialog window."""
    def __init__(self, parent, msg="Installiere OVMF Firmware Dateien..."):
        super().__init__(title="Bitte warten", transient_for=parent)
        self.set_modal(True)
        self.set_default_size(300,100)
        box = self.get_content_area()
        box.add(Gtk.Label(label=msg))
        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(False)
        box.add(self.progress)
        self.show_all()
        self.timeout_id = GLib.timeout_add(100, self.on_timeout)
    def on_timeout(self):
        """Pulses the progress bar."""
        self.progress.pulse()
        return True
    def destroy(self):
        """Destroys the loading dialog, removing timeout."""
        GLib.source_remove(self.timeout_id)
        super().destroy()

#### ISO SELECT DIALOG ####
class ISOSelectDialog(Gtk.Window):
    """ISO selection dialog."""
    def __init__(self, parent):
        super().__init__(title="ISO auswählen", transient_for=parent)
        self.parent = parent
        self.set_default_size(400,300)
        self.set_position(Gtk.WindowPosition.CENTER)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(20)
        vbox.set_margin_bottom(20)
        vbox.set_margin_start(20)
        vbox.set_margin_end(20)
        btn = Gtk.Button(label="+")
        btn.set_size_request(150,150)
        btn.connect("clicked", self.on_plus_clicked)
        vbox.pack_start(btn, False, False, 0)
        drop = Gtk.EventBox()
        drop.set_size_request(300,150)
        drop.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.9,0.9,0.9,1))
        drop.connect("drag-data-received", self.on_drag_received)
        drop.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        target = Gtk.TargetEntry.new("text/uri-list", 0, 0)
        drop.drag_dest_set_target_list(Gtk.TargetList.new([target]))
        vbox.pack_start(drop, True, True, 0)
        vbox.pack_start(Gtk.Label(label="Ziehen Sie Ihre ISO-Datei hierhin oder klicken Sie auf '+'"), False, False, 0)
        self.add(vbox)
    def on_plus_clicked(self, w):
        """Handles '+' button click to open file chooser."""
        d = Gtk.FileChooserDialog(title="ISO-Datei auswählen", parent=self,
                                        action=Gtk.FileChooserAction.OPEN)
        d.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        f = Gtk.FileFilter()
        f.set_name("ISO-Dateien")
        f.add_pattern("*.iso")
        d.add_filter(f)
        if d.run() == Gtk.ResponseType.OK:
            self.iso_chosen(d.get_filename())
        d.destroy()
    def on_drag_received(self, w, dc, x, y, data, info, time):
        """Handles drag and drop of ISO file."""
        uris = data.get_uris()
        if uris:
            self.iso_chosen(uris[0].replace("file://", "").strip())
    def iso_chosen(self, iso_path):
        """Closes dialog and opens VM create dialog with chosen ISO."""
        self.destroy()
        d = VMCreateDialog(self.parent, iso_path)
        if d.run() == Gtk.ResponseType.OK:
            self.parent.add_vm(d.get_vm_config())
        d.destroy()

#### NEW VM DIALOG ####
class VMCreateDialog(Gtk.Dialog):
    """New VM creation dialog.
    This dialog is opened after an ISO file has been selected in the ISOSelectDialog.
    It allows the user to configure the VM parameters, excluding ISO selection which is already done.
    """
    def __init__(self, parent, iso_path=None):
        super().__init__(title="Neue VM Konfiguration", transient_for=parent)
        self.set_default_size(500,500)
        self.iso_path = iso_path
        box = self.get_content_area()
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)
        grid.attach(Gtk.Label(label="VM Name:"), 0, 0, 1, 1)
        self.entry_name = Gtk.Entry()
        grid.attach(self.entry_name, 1, 0, 2, 1)
        grid.attach(Gtk.Label(label="VM Verzeichnis:"), 0, 1, 1, 1)
        self.entry_path = Gtk.Entry()
        btn = Gtk.Button(label="Durchsuchen")
        btn.connect("clicked", self.on_browse)
        grid.attach(self.entry_path, 1, 1, 1, 1)
        grid.attach(btn, 2, 1, 1, 1)
        grid.attach(Gtk.Label(label="CPU-Kerne:"), 0, 2, 1, 1)
        self.spin_cpu = Gtk.SpinButton.new_with_range(1, 32, 1)
        self.spin_cpu.set_value(2)
        grid.attach(self.spin_cpu, 1, 2, 2, 1)
        grid.attach(Gtk.Label(label="RAM (MiB):"), 0, 3, 1, 1)
        self.spin_ram = Gtk.SpinButton.new_with_range(256, 131072, 256)
        self.spin_ram.set_value(4096)
        grid.attach(self.spin_ram, 1, 3, 2, 1)
        grid.attach(Gtk.Label(label="Festplattengröße (GB):"), 0, 4, 1, 1)
        self.spin_disk = Gtk.SpinButton.new_with_range(1, 128, 1)
        self.spin_disk.set_value(40)
        grid.attach(self.spin_disk, 1, 4, 2, 1)
        grid.attach(Gtk.Label(label="Festplattentyp:"), 0, 5, 1, 1)
        self.radio_qcow2 = Gtk.RadioButton.new_with_label_from_widget(None, "qcow2 (Empfohlen)")
        self.radio_raw = Gtk.RadioButton.new_with_label_from_widget(self.radio_qcow2, "raw (Voll)")
        grid.attach(self.radio_qcow2, 1, 5, 1, 1)
        grid.attach(self.radio_raw, 2, 5, 1, 1)
        grid.attach(Gtk.Label(label="Firmware:"), 0, 6, 1, 1)
        fw_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.radio_bios = Gtk.RadioButton.new_with_label_from_widget(None, "BIOS")
        self.radio_uefi = Gtk.RadioButton.new_with_label_from_widget(self.radio_bios, "UEFI")
        self.radio_secure = Gtk.RadioButton.new_with_label_from_widget(self.radio_bios, "UEFI+Secure Boot")
        fw_box.pack_start(self.radio_bios, False, False, 0)
        fw_box.pack_start(self.radio_uefi, False, False, 0)
        fw_box.pack_start(self.radio_secure, False, False, 0)
        grid.attach(fw_box, 1, 6, 2, 1)
        grid.attach(Gtk.Label(label="TPM aktivieren:"), 0, 7, 1, 1)
        self.check_tpm = Gtk.CheckButton()
        grid.attach(self.check_tpm, 1, 7, 2, 1)
        grid.attach(Gtk.Label(label="Anzeige:"), 0, 8, 1, 1)
        self.combo_disp = Gtk.ComboBoxText()
        for opt in ["gtk (default)", "virtio", "spice (virtio)", "qemu"]:
            self.combo_disp.append_text(opt)
        self.combo_disp.set_active(0)
        grid.attach(self.combo_disp, 1, 8, 2, 1)
        grid.attach(Gtk.Label(label="3D-Beschleunigung:"), 0, 9, 1, 1)
        self.check_3d = Gtk.CheckButton()
        grid.attach(self.check_3d, 1, 9, 2, 1)

        box.add(grid)
        self.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        self.add_button("Erstellen", Gtk.ResponseType.OK)
        self.show_all()
        self.initial_firmware = "BIOS"
        if self.radio_uefi.get_active():
            self.initial_firmware = "UEFI"
        elif self.radio_secure.get_active():
            self.initial_firmware = "UEFI+Secure Boot"

    def on_browse(self, w):
        """Handles browse button click for VM directory."""
        d = Gtk.FileChooserDialog(title="VM-Verzeichnis auswählen", parent=self,
                                        action=Gtk.FileChooserAction.SELECT_FOLDER)
        d.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Auswählen", Gtk.ResponseType.OK)
        if d.run() == Gtk.ResponseType.OK:
            self.entry_path.set_text(d.get_filename())
        d.destroy()

    def get_vm_config(self):
        """Gets VM configuration from dialog."""
        firmware = "BIOS"
        if self.radio_uefi.get_active():
            firmware = "UEFI"
        elif self.radio_secure.get_active():
            firmware = "UEFI+Secure Boot"
        config = {
            "name": self.entry_name.get_text(),
            "path": self.entry_path.get_text(),
            "cpu": self.spin_cpu.get_value_as_int(),
            "ram": self.spin_ram.get_value_as_int(),
            "disk": self.spin_disk.get_value_as_int(),
            "disk_type": "qcow2" if self.radio_qcow2.get_active() else "raw",
            "firmware": firmware,
            "display": self.combo_disp.get_active_text(),
            "iso": self.iso_path if self.iso_path else "",
            "iso_enabled": True if self.iso_path else False,
            "3d_acceleration": self.check_3d.get_active(),
            "disk_image": os.path.join(self.entry_path.get_text(), self.entry_name.get_text() + ".img"),
            "tpm_enabled": self.check_tpm.get_active()
        }
        if not os.path.exists(config["disk_image"]):
            qemu_img = shutil.which("qemu-img")
            if qemu_img:
                try:
                    # Ausgabe nach /dev/null umleiten
                    subprocess.run([qemu_img, "create", "-f", config["disk_type"],
                                             config["disk_image"], f"{config['disk']}G"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception as e_img_create:
                    show_error_dialog(f"Fehler beim Erstellen des Festplattenabbilds: {e_img_create}", self) # Parent is self (VMCreateDialog)
                    return None # Return None to indicate failure


        if config["firmware"] in ["UEFI", "UEFI+Secure Boot"]:
            ovmf_dir = os.path.join(config["path"], "ovmf")
            os.makedirs(ovmf_dir, exist_ok=True)
            if self.initial_firmware == "BIOS":
                if not copy_uefi_files(config, self): # Pass dialog as parent for sudo prompt and error dialog
                    return None # Return None if copying fails
        elif self.initial_firmware in ["UEFI", "UEFI+Secure Boot"]:
            delete_ovmf_dir(config)
        config["launch_cmd"] = build_launch_command(config)
        return config

#### VM SETTINGS DIALOG ####
class VMSettingsDialog(Gtk.Dialog):
    """VM settings dialog."""
    def __init__(self, parent, config):
        super().__init__(title="VM-Einstellungen bearbeiten", transient_for=parent)
        self.set_default_size(500,400)
        self.config = config.copy()
        box = self.get_content_area()
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)

        # ISO aktivieren Checkbox (ohne Label, rechts vom Browse Button)
        self.check_iso_enable = Gtk.CheckButton()
        self.check_iso_enable.set_active(self.config.get("iso_enabled", False) )
        self.check_iso_enable.connect("toggled", self.on_iso_enabled_toggled_settings)

        grid.attach(Gtk.Label(label="ISO-Pfad:"), 0, 0, 1, 1) # ISO Pfad Label in Spalte 0, Reihe 0
        self.entry_iso = Gtk.Entry(text=self.config.get("iso", ""))
        grid.attach(self.entry_iso, 1, 0, 1, 1) # ISO Pfad Entry in Spalte 1, Reihe 0
        self.btn_iso_browse = Gtk.Button(label="Durchsuchen")
        self.btn_iso_browse.connect("clicked", self.on_iso_browse)
        grid.attach(self.btn_iso_browse, 2, 0, 1, 1) # Browse Button in Spalte 2, Reihe 0
        grid.attach(self.check_iso_enable, 3, 0, 1, 1) # Checkbox rechts vom Browse Button in Spalte 3, Reihe 0

        grid.attach(Gtk.Label(label="CPU-Kerne:"), 0, 1, 1, 1)
        self.spin_cpu = Gtk.SpinButton.new_with_range(1,32,1)
        self.spin_cpu.set_value(self.config.get("cpu", 2))
        grid.attach(self.spin_cpu, 1, 1, 2, 1)
        grid.attach(Gtk.Label(label="RAM (MiB):"), 0, 2, 1, 1)
        self.spin_ram = Gtk.SpinButton.new_with_range(256,131072,256)
        self.spin_ram.set_value(self.config.get("ram", 4096))
        grid.attach(self.spin_ram, 1, 2, 2, 1)
        grid.attach(Gtk.Label(label="Firmware:"), 0, 3, 1, 1)
        fw_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.radio_bios = Gtk.RadioButton.new_with_label_from_widget(None, "BIOS")
        self.radio_uefi = Gtk.RadioButton.new_with_label_from_widget(self.radio_bios, "UEFI")
        self.radio_secure = Gtk.RadioButton.new_with_label_from_widget(self.radio_bios, "UEFI+Secure Boot")
        fw_box.pack_start(self.radio_bios, False, False, 0)
        fw_box.pack_start(self.radio_uefi, False, False, 0)
        fw_box.pack_start(self.radio_secure, False, False, 0)
        if self.config.get("firmware", "BIOS") == "UEFI":
            self.radio_uefi.set_active(True)
        elif self.config.get("firmware") == "UEFI+Secure Boot":
            self.radio_secure.set_active(True)
        else:
            self.radio_bios.set_active(True)
        grid.attach(fw_box, 1, 3, 2, 1)
        grid.attach(Gtk.Label(label="TPM aktivieren:"), 0, 4, 1, 1)
        self.check_tpm = Gtk.CheckButton()
        self.check_tpm.set_active(self.config.get("tpm_enabled", False))
        grid.attach(self.check_tpm, 1, 4, 2, 1)
        grid.attach(Gtk.Label(label="Anzeige:"), 0, 5, 1, 1)
        self.combo_disp = Gtk.ComboBoxText()
        for opt in ["gtk (default)", "virtio", "spice (virtio)", "qemu"]:
            self.combo_disp.append_text(opt)
        self.combo_disp.set_active(0)
        if self.config.get("display") in ["gtk (default)", "virtio", "spice (virtio)", "qemu"]:
            self.combo_disp.set_active(["gtk (default)", "virtio", "spice (virtio)", "qemu"].index(self.config.get("display")))
        grid.attach(self.combo_disp, 1, 5, 2, 1)
        grid.attach(Gtk.Label(label="3D-Beschleunigung:"), 0, 6, 1, 1)
        self.check_3d = Gtk.CheckButton()
        self.check_3d.set_active(self.config.get("3d_acceleration", False))
        grid.attach(self.check_3d, 1, 6, 2, 1)
        box.add(grid)
        self.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        self.add_button("Anwenden", Gtk.ResponseType.OK)
        self.show_all()
        self.initial_firmware = self.config.get("firmware", "BIOS")
        self.update_iso_entry_sensitivity_settings()

    def on_iso_enabled_toggled_settings(self, check):
        """Handles ISO enable checkbox toggling in settings dialog."""
        self.update_iso_entry_sensitivity_settings()

    def update_iso_entry_sensitivity_settings(self):
        """Updates sensitivity of ISO path entry based on checkbox in settings dialog."""
        is_enabled = self.check_iso_enable.get_active()
        self.entry_iso.set_sensitive(is_enabled)
        self.btn_iso_browse.set_sensitive(is_enabled)

    def on_iso_browse(self, w):
        """Handles ISO browse button click in settings dialog."""
        d = Gtk.FileChooserDialog(title="ISO-Datei auswählen", parent=self,
                                        action=Gtk.FileChooserAction.OPEN)
        d.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        f = Gtk.FileFilter()
        f.set_name("ISO-Dateien")
        f.add_pattern("*.iso")
        d.add_filter(f)
        if d.run() == Gtk.ResponseType.OK:
            self.entry_iso.set_text(d.get_filename())
        d.destroy()
    def get_updated_config(self):
        """Gets updated VM configuration from settings dialog."""
        firmware = "BIOS"
        if self.radio_uefi.get_active():
            firmware = "UEFI"
        elif self.radio_secure.get_active():
            firmware = "UEFI+Secure Boot"
        self.config["iso"] = urllib.parse.unquote(self.entry_iso.get_text()) if self.check_iso_enable.get_active() else ""
        self.config["iso_enabled"] = self.check_iso_enable.get_active()
        self.config["cpu"] = self.spin_cpu.get_value_as_int()
        self.config["ram"] = self.spin_ram.get_value_as_int()
        if self.config["firmware"] != firmware:
            if firmware in ["UEFI", "UEFI+Secure Boot"]:
                if not copy_uefi_files(self.config, self): # Pass 'self' (settings dialog) as parent window for sudo prompt
                    show_error_dialog("Fehler beim Kopieren der UEFI Firmware Dateien. Überprüfen Sie Berechtigungen oder Installation.", self)
                    return None
            else:
                delete_ovmf_dir(self.config)
        self.config["firmware"] = firmware
        self.config["display"] = self.combo_disp.get_active_text()
        self.config["3d_acceleration"] = self.check_3d.get_active()
        self.config["tpm_enabled"] = self.check_tpm.get_active()
        self.config["launch_cmd"] = build_launch_command(self.config)
        return self.config

#### VM CLONE DIALOG ####
class VMCloneDialog(Gtk.Dialog):
    """VM clone dialog window."""
    def __init__(self, parent, vm_config):
        super().__init__(title="VM Klonen", transient_for=parent)
        self.set_default_size(400,200)
        self.original_vm = vm_config
        box = self.get_content_area()
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)
        grid.attach(Gtk.Label(label="Neuer VM-Name:"), 0, 0, 1, 1)
        self.entry_new_name = Gtk.Entry(text=self.original_vm["name"] + "_clone")
        grid.attach(self.entry_new_name, 1, 0, 2, 1)
        grid.attach(Gtk.Label(label="Neues Verzeichnis:"), 0, 1, 1, 1)
        self.entry_new_path = Gtk.Entry()
        btn = Gtk.Button(label="Durchsuchen")
        btn.connect("clicked", self.on_browse)
        grid.attach(self.entry_new_path, 1, 1, 1, 1)
        grid.attach(btn, 2, 1, 1, 1)
        box.add(grid)
        self.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        self.add_button("Klonen", Gtk.ResponseType.OK)
        self.show_all()
    def on_browse(self, w):
        """Handles browse button click for clone destination directory."""
        d = Gtk.FileChooserDialog(title="Zielordner auswählen", parent=self,
                                        action=Gtk.FileChooserAction.SELECT_FOLDER)
        d.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Auswählen", Gtk.ResponseType.OK)
        if d.run() == Gtk.ResponseType.OK:
            self.entry_new_path.set_text(d.get_filename())
        d.destroy()
    def get_clone_info(self):
        """Gets clone information from dialog."""
        return {"new_name": self.entry_new_name.get_text(), "new_path": self.entry_new_path.get_text()}

#### MAIN WINDOW ####
class QEMUManagerMain(Gtk.Window):
    """Main application window."""
    def __init__(self):
        super().__init__(title="QEMU VM Manager")
        self.set_default_size(600,400)
        self.vm_configs = load_all_vm_configs()
        self.build_ui()
        self.apply_css()
    def build_ui(self):
        """Builds main window UI."""
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(10)
        vbox.set_margin_bottom(10)
        vbox.set_margin_start(10)
        vbox.set_margin_end(10)
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        self.set_titlebar(header)
        btn_add = Gtk.Button(label="+")
        btn_add.connect("clicked", self.on_add_vm)
        header.pack_end(btn_add)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self.listbox)
        vbox.pack_start(scrolled, True, True, 0)
        self.add(vbox)
        self.refresh_vm_list()
    def apply_css(self):
        """Applies CSS styling."""
        css = b"""
        window { background-color: rgba(255,255,255,0.15); }
        .vm-item { background-color: rgba(50,50,50,0.8); border: 2px solid #555; border-radius: 4px; padding: 5px; margin: 5px; }
        .vm-item label { color: #fff; font-weight: bold; }
        .round-button { border-radius: 16px; padding: 0; background-color: transparent; }
        .iso-drop-area { background-color: rgba(0.9,0.9,0.9,1); }
        """
        sp = Gtk.CssProvider()
        sp.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), sp, Gtk.STYLE_PROVIDER_PRIORITY_USER)
    def on_add_vm(self, w):
        """Handles add VM button click."""
        d = ISOSelectDialog(self)
        d.show_all()
    def add_vm(self, config):
        """Adds new VM configuration."""
        if config is None: # Handle None config if UEFI copy fails
            return
        save_vm_config(config)
        index = load_vm_index()
        if config["path"] not in index:
            index.append(config["path"])
            save_vm_index(index)
        self.vm_configs = load_all_vm_configs()
        self.refresh_vm_list()
    def refresh_vm_list(self):
        """Refreshes VM list display."""
        for row in self.listbox.get_children():
            self.listbox.remove(row)
        for vm in self.vm_configs:
            row = self.create_vm_row(vm)
            self.listbox.add(row)
        self.listbox.show_all()
    def create_vm_row(self, vm):
        """Creates row for VM list."""
        row = Gtk.ListBoxRow()
        row.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        hbox.get_style_context().add_class("vm-item")
        label = Gtk.Label(label=vm["name"])
        label.set_xalign(0.0)
        hbox.pack_start(label, True, True, 0)
        play_btn = Gtk.Button()
        play_btn.set_relief(Gtk.ReliefStyle.NONE)
        play_btn.set_size_request(32,32)
        play_img = Gtk.Image.new_from_icon_name("media-playback-start", Gtk.IconSize.BUTTON)
        play_btn.set_image(play_img)
        play_btn.get_style_context().add_class("round-button")
        play_btn.connect("clicked", lambda b, vm=vm: self.start_vm(vm))
        settings_btn = Gtk.Button()
        settings_btn.set_relief(Gtk.ReliefStyle.NONE)
        settings_btn.set_size_request(32,32)
        set_img = Gtk.Image.new_from_icon_name("preferences-system", Gtk.IconSize.BUTTON)
        settings_btn.set_image(set_img)
        settings_btn.get_style_context().add_class("round-button")
        settings_btn.connect("clicked", lambda b, vm=vm: self.edit_vm(vm))
        hbox.pack_end(settings_btn, False, False, 0)
        hbox.pack_end(play_btn, False, False, 0)
        row.add(hbox)
        row.connect("button-press-event", self.on_vm_item_event, vm)
        return row
    def on_vm_item_event(self, w, event, vm):
        """Handles VM item right-click menu."""
        if event.button == 3:
            menu = self.create_context_menu(vm)
            menu.popup_at_pointer(event)
    def create_context_menu(self, vm):
        """Creates VM context menu."""
        menu = Gtk.Menu()
        item_start = Gtk.MenuItem(label="Starten")
        item_settings = Gtk.MenuItem(label="Einstellungen")
        item_delete = Gtk.MenuItem(label="Löschen")
        item_clone = Gtk.MenuItem(label="Klonen")
        item_start.connect("activate", lambda b, vm=vm: self.start_vm(vm))
        item_settings.connect("activate", lambda b, vm=vm: self.edit_vm(vm))
        item_delete.connect("activate", lambda b, vm=vm: self.delete_vm(vm))
        item_clone.connect("activate", lambda b, vm=vm: self.clone_vm(vm))
        menu.append(item_start)
        menu.append(item_settings)
        menu.append(item_delete)
        menu.append(item_clone)
        menu.show_all()
        return menu
    def start_vm(self, vm):
        """Starts selected VM."""
        launch_cmd = build_launch_command(vm)
        if not launch_cmd:
            return # build_launch_command already shows error dialog if qemu not found
        disk = vm["disk_image"]
        if not os.path.exists(disk):
            img = shutil.which("qemu-img")
            if not img:
                show_error_dialog("qemu-img Binärdatei nicht gefunden! \nErforderlich, um Festplattenabbilder zu erstellen.", main_win)
                return
            disk_type = vm["disk_type"]
            disk_size = vm["disk"]
            try:
                # Ausgabe nach /dev/null umleiten
                subprocess.run([img, "create", "-f", disk_type,
                                         disk, f"{disk_size}G"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e_img_create:
                show_error_dialog(f"Fehler beim Erstellen des Festplattenabbilds: {disk} - {e_img_create}", main_win)
                return
        threading.Thread(target=lambda cmd: subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), args=(launch_cmd,)).start() # Redirect output here as well
    def edit_vm(self, vm):
        """Opens VM settings dialog."""
        d = VMSettingsDialog(self, vm)
        if d.run() == Gtk.ResponseType.OK:
            updated_config = d.get_updated_config()
            if updated_config:
                save_vm_config(updated_config)
                self.vm_configs = load_all_vm_configs()
                self.refresh_vm_list()
        d.destroy()
    def clone_vm(self, vm):
        """Clones selected VM."""
        d = VMCloneDialog(self, vm)
        if d.run() == Gtk.ResponseType.OK:
            clone_info = d.get_clone_info()
            if clone_info:
                self.perform_clone_vm(vm, clone_info)
        d.destroy()
    def perform_clone_vm(self, vm, clone_info):
        """Performs VM cloning operation."""
        new_vm_name = clone_info["new_name"]
        new_vm_path = os.path.join(clone_info["new_path"], new_vm_name)
        if os.path.exists(new_vm_path):
            show_error_dialog(f"Verzeichnis existiert bereits: {new_vm_path}", main_win)
            return
        try:
            shutil.copytree(vm["path"], new_vm_path)
        except Exception as e:
            show_error_dialog(f"Fehler beim Klonen des VM-Verzeichnisses: {e}", main_win)
            return
        new_config_path = os.path.join(new_vm_path, f"{vm['name']}.json")
        new_config_file = os.path.join(new_vm_path, f"{new_vm_name}.json")
        os.rename(new_config_path, new_config_file)
        with open(new_config_file, "r") as f:
            new_config = json.load(f)
        new_config["name"] = new_vm_name
        new_config["path"] = new_vm_path
        new_config["disk_image"] = os.path.join(new_vm_path, new_vm_name + ".img")
        with open(new_config_file, "w") as f:
            json.dump(new_config, f, indent=4)
        index = load_vm_index()
        if new_vm_path not in index:
            index.append(new_vm_path)
            save_vm_index(index)
        self.vm_configs = load_all_vm_configs()
        self.refresh_vm_list()
    def delete_vm(self, vm):
        """Deletes selected VM."""
        dialog = Gtk.MessageDialog(transient_for=self, flags=0,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.YES_NO,
                text=f"VM '{vm['name']}' löschen?")
        resp = dialog.run()
        dialog.destroy()
        if resp == Gtk.ResponseType.YES:
            try:
                shutil.rmtree(vm["path"])
                index = load_vm_index()
                if vm["path"] in index:
                    index.remove(vm["path"])
                    save_vm_index(index)
                self.vm_configs = load_all_vm_configs()
                self.refresh_vm_list()
            except Exception as e:
                show_error_dialog(f"Fehler beim Löschen der VM: {e}", main_win)

def show_error_dialog(msg, parent=None):
    """Shows error message dialog."""
    dialog = Gtk.MessageDialog(transient_for=parent, flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=msg)
    dialog.run()
    dialog.destroy()

if __name__ == '__main__':
    main_win = QEMUManagerMain()
    main_win.connect("destroy", Gtk.main_quit)
    main_win.show_all()
    Gtk.main()
