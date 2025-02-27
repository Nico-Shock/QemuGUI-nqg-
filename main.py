#!/usr/bin/env python3
import os
import json
import subprocess
import shutil
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk

# -------------------------------------------------------------------
# Globale Konfiguration (Speicherung im Benutzerverzeichnis)
# -------------------------------------------------------------------
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".qemu_manager")
if not os.path.exists(CONFIG_DIR):
    os.makedirs(CONFIG_DIR)
INDEX_FILE = os.path.join(CONFIG_DIR, "vms_index.json")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# -------------------------------------------------------------------
# Funktion zum Auffinden von OVMF-Dateien für UEFI/UEFI+Secure Boot
# -------------------------------------------------------------------
def get_ovmf_files(secure=False):
    search_dirs = ["/usr/share/OVMF", "/usr/local/share/OVMF", BASE_DIR]
    for d in search_dirs:
        ovmf_code = os.path.join(d, "OVMF_CODE.fd")
        if secure:
            ovmf_vars = os.path.join(d, "OVMF_VARS_SECURE.fd")
        else:
            ovmf_vars = os.path.join(d, "OVMF_VARS.fd")
        if os.path.exists(ovmf_code) and os.path.exists(ovmf_vars):
            return ovmf_code, ovmf_vars
    return None, None

# -------------------------------------------------------------------
# Funktionen zum Laden und Speichern der VM-Konfigurationen
# -------------------------------------------------------------------
def load_vm_index():
    if os.path.exists(INDEX_FILE) and os.path.getsize(INDEX_FILE) > 0:
        try:
            with open(INDEX_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print("Fehler beim Laden des Index:", e)
            return []
    return []

def save_vm_index(index):
    with open(INDEX_FILE, "w") as f:
        json.dump(index, f, indent=4)

def load_all_vm_configs():
    index = load_vm_index()
    configs = []
    for vm_dir in index:
        config_file = os.path.join(vm_dir, "vm_config.json")
        if os.path.exists(config_file):
            try:
                with open(config_file, "r") as f:
                    config = json.load(f)
                    configs.append(config)
            except Exception as e:
                print("Fehler beim Laden der VM-Konfiguration:", e)
    return configs

def save_vm_config(config):
    config_path = os.path.join(config["path"], "vm_config.json")
    try:
        with open(config_path, "w") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        dialog = Gtk.MessageDialog(
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Fehler beim Speichern der VM-Konfiguration.\nBitte prüfe die Berechtigungen."
        )
        dialog.run()
        dialog.destroy()
        raise e

# -------------------------------------------------------------------
# Dialog zur ISO-Auswahl (Drag & Drop und Plus-Button)
# -------------------------------------------------------------------
class ISOSelectDialog(Gtk.Window):
    def __init__(self, parent):
        super().__init__(title="ISO auswählen")
        self.parent = parent
        self.set_default_size(400, 300)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(20)
        vbox.set_margin_bottom(20)
        vbox.set_margin_start(20)
        vbox.set_margin_end(20)

        # Plus-Button als visuelle Hilfe
        plus_button = Gtk.Button(label="+")
        plus_button.set_size_request(150, 150)
        plus_button.connect("clicked", self.on_plus_clicked)
        vbox.pack_start(plus_button, False, False, 0)

        # Drag & Drop Fläche
        drop_area = Gtk.EventBox()
        drop_area.set_size_request(300, 150)
        drop_area.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.9, 0.9, 0.9, 1))
        drop_area.connect("drag-data-received", self.on_drag_received)
        drop_area.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        target_entry = Gtk.TargetEntry.new("text/uri-list", 0, 0)
        drop_area.drag_dest_set_target_list(Gtk.TargetList.new([target_entry]))
        vbox.pack_start(drop_area, True, True, 0)

        info_label = Gtk.Label(label="Ziehen Sie eine ISO-Datei hierher oder klicken Sie auf '+'")
        vbox.pack_start(info_label, False, False, 0)

        self.add(vbox)

    def on_plus_clicked(self, widget):
        dialog = Gtk.FileChooserDialog(title="Wähle ISO-Datei", parent=self,
                                       action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        iso_filter = Gtk.FileFilter()
        iso_filter.set_name("ISO Dateien")
        iso_filter.add_pattern("*.iso")
        dialog.add_filter(iso_filter)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            iso_path = dialog.get_filename()
            self.iso_chosen(iso_path)
        dialog.destroy()

    def on_drag_received(self, widget, drag_context, x, y, data, info, time):
        uris = data.get_uris()
        if uris:
            iso_path = uris[0].replace("file://", "").strip()
            self.iso_chosen(iso_path)

    def iso_chosen(self, iso_path):
        self.destroy()
        vm_dialog = VMCreateDialog(self.parent, iso_path)
        response = vm_dialog.run()
        if response == Gtk.ResponseType.OK:
            config = vm_dialog.get_vm_config()
            self.parent.add_vm(config)
        vm_dialog.destroy()

# -------------------------------------------------------------------
# Dialog zur Erstellung einer neuen VM
# -------------------------------------------------------------------
class VMCreateDialog(Gtk.Dialog):
    def __init__(self, parent, iso_path=None):
        super().__init__(title="Neue VM Konfiguration", transient_for=parent)
        self.set_default_size(500, 500)
        self.iso_path = iso_path
        box = self.get_content_area()

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)

        # VM Name
        lbl_name = Gtk.Label(label="VM Name:")
        self.entry_name = Gtk.Entry()
        grid.attach(lbl_name, 0, 0, 1, 1)
        grid.attach(self.entry_name, 1, 0, 2, 1)

        # VM Verzeichnis
        lbl_path = Gtk.Label(label="VM Pfad:")
        self.entry_path = Gtk.Entry()
        btn_browse = Gtk.Button(label="Durchsuchen")
        btn_browse.connect("clicked", self.on_browse)
        grid.attach(lbl_path, 0, 1, 1, 1)
        grid.attach(self.entry_path, 1, 1, 1, 1)
        grid.attach(btn_browse, 2, 1, 1, 1)

        # CPU Kerne
        lbl_cpu = Gtk.Label(label="CPU Kerne:")
        self.spin_cpu = Gtk.SpinButton.new_with_range(1, 32, 1)
        self.spin_cpu.set_value(2)
        grid.attach(lbl_cpu, 0, 2, 1, 1)
        grid.attach(self.spin_cpu, 1, 2, 2, 1)

        # RAM (MiB)
        lbl_ram = Gtk.Label(label="RAM (MiB):")
        self.spin_ram = Gtk.SpinButton.new_with_range(256, 131072, 256)
        self.spin_ram.set_value(4096)
        grid.attach(lbl_ram, 0, 3, 1, 1)
        grid.attach(self.spin_ram, 1, 3, 2, 1)

        # Festplattengröße (GB)
        lbl_disk = Gtk.Label(label="Festplattengröße (GB):")
        self.spin_disk = Gtk.SpinButton.new_with_range(1, 128, 1)
        self.spin_disk.set_value(40)
        grid.attach(lbl_disk, 0, 4, 1, 1)
        grid.attach(self.spin_disk, 1, 4, 2, 1)

        # Festplattentyp
        lbl_disk_type = Gtk.Label(label="Festplattentyp:")
        self.radio_qcow2 = Gtk.RadioButton.new_with_label_from_widget(None, "qcow2 (Empfohlen)")
        self.radio_raw = Gtk.RadioButton.new_with_label_from_widget(self.radio_qcow2, "raw (Vollständig)")
        grid.attach(lbl_disk_type, 0, 5, 1, 1)
        grid.attach(self.radio_qcow2, 1, 5, 1, 1)
        grid.attach(self.radio_raw, 2, 5, 1, 1)

        # Firmware Auswahl
        lbl_fw = Gtk.Label(label="Firmware:")
        fw_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.radio_bios = Gtk.RadioButton.new_with_label_from_widget(None, "BIOS")
        self.radio_uefi = Gtk.RadioButton.new_with_label_from_widget(self.radio_bios, "UEFI")
        self.radio_secure = Gtk.RadioButton.new_with_label_from_widget(self.radio_bios, "UEFI+Secure Boot")
        fw_box.pack_start(self.radio_bios, False, False, 0)
        fw_box.pack_start(self.radio_uefi, False, False, 0)
        fw_box.pack_start(self.radio_secure, False, False, 0)
        grid.attach(lbl_fw, 0, 6, 1, 1)
        grid.attach(fw_box, 1, 6, 2, 1)

        # Display Auswahl
        lbl_disp = Gtk.Label(label="Display:")
        self.combo_disp = Gtk.ComboBoxText()
        self.combo_disp.append_text("gtk (default)")
        self.combo_disp.append_text("qxl")
        self.combo_disp.append_text("spice")
        self.combo_disp.set_active(0)
        grid.attach(lbl_disp, 0, 7, 1, 1)
        grid.attach(self.combo_disp, 1, 7, 2, 1)

        # 3D Beschleunigung
        lbl_3d = Gtk.Label(label="3D Beschleunigung:")
        self.check_3d = Gtk.CheckButton()
        grid.attach(lbl_3d, 0, 8, 1, 1)
        grid.attach(self.check_3d, 1, 8, 2, 1)

        box.add(grid)
        self.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        self.add_button("Erstellen", Gtk.ResponseType.OK)
        self.show_all()

    def on_browse(self, widget):
        dialog = Gtk.FileChooserDialog(title="VM Verzeichnis auswählen", parent=self,
                                       action=Gtk.FileChooserAction.SELECT_FOLDER)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           "Auswählen", Gtk.ResponseType.OK)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.entry_path.set_text(dialog.get_filename())
        dialog.destroy()

    def get_vm_config(self):
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
            "iso": self.iso_path,
            "3d_acceleration": self.check_3d.get_active()
        }
        config["disk_image"] = os.path.join(config["path"], config["name"] + ".img")
        return config

# -------------------------------------------------------------------
# Dialog zur Bearbeitung bestehender VM-Einstellungen
# -------------------------------------------------------------------
class VMSettingsDialog(Gtk.Dialog):
    def __init__(self, parent, config):
        super().__init__(title="VM Einstellungen bearbeiten", transient_for=parent)
        self.set_default_size(500, 400)
        self.config = config.copy()
        box = self.get_content_area()

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)

        lbl_iso = Gtk.Label(label="ISO Pfad:")
        self.entry_iso = Gtk.Entry(text=self.config.get("iso", ""))
        grid.attach(lbl_iso, 0, 0, 1, 1)
        grid.attach(self.entry_iso, 1, 0, 2, 1)

        lbl_cpu = Gtk.Label(label="CPU Kerne:")
        self.spin_cpu = Gtk.SpinButton.new_with_range(1, 32, 1)
        self.spin_cpu.set_value(self.config.get("cpu", 2))
        grid.attach(lbl_cpu, 0, 1, 1, 1)
        grid.attach(self.spin_cpu, 1, 1, 2, 1)

        lbl_ram = Gtk.Label(label="RAM (MiB):")
        self.spin_ram = Gtk.SpinButton.new_with_range(256, 131072, 256)
        self.spin_ram.set_value(self.config.get("ram", 4096))
        grid.attach(lbl_ram, 0, 2, 1, 1)
        grid.attach(self.spin_ram, 1, 2, 2, 1)

        lbl_fw = Gtk.Label(label="Firmware:")
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
        grid.attach(lbl_fw, 0, 3, 1, 1)
        grid.attach(fw_box, 1, 3, 2, 1)

        lbl_disp = Gtk.Label(label="Display:")
        self.combo_disp = Gtk.ComboBoxText()
        self.combo_disp.append_text("gtk (default)")
        self.combo_disp.append_text("qxl")
        self.combo_disp.append_text("spice")
        self.combo_disp.set_active(0)
        grid.attach(lbl_disp, 0, 4, 1, 1)
        grid.attach(self.combo_disp, 1, 4, 2, 1)

        lbl_3d = Gtk.Label(label="3D Beschleunigung:")
        self.check_3d = Gtk.CheckButton()
        self.check_3d.set_active(self.config.get("3d_acceleration", False))
        grid.attach(lbl_3d, 0, 5, 1, 1)
        grid.attach(self.check_3d, 1, 5, 2, 1)

        box.add(grid)
        self.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        self.add_button("Speichern", Gtk.ResponseType.OK)
        self.show_all()

    def get_updated_config(self):
        firmware = "BIOS"
        if self.radio_uefi.get_active():
            firmware = "UEFI"
        elif self.radio_secure.get_active():
            firmware = "UEFI+Secure Boot"
        self.config["iso"] = self.entry_iso.get_text()
        self.config["cpu"] = self.spin_cpu.get_value_as_int()
        self.config["ram"] = self.spin_ram.get_value_as_int()
        self.config["firmware"] = firmware
        self.config["display"] = self.combo_disp.get_active_text()
        self.config["3d_acceleration"] = self.check_3d.get_active()
        return self.config

# -------------------------------------------------------------------
# Dialog zum Klonen einer VM
# -------------------------------------------------------------------
class VMCloneDialog(Gtk.Dialog):
    def __init__(self, parent, vm_config):
        super().__init__(title="VM klonen", transient_for=parent)
        self.set_default_size(400, 200)
        self.original_vm = vm_config
        box = self.get_content_area()

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)

        lbl_new_name = Gtk.Label(label="Neuer VM Name:")
        self.entry_new_name = Gtk.Entry(text=self.original_vm["name"] + "_clone")
        grid.attach(lbl_new_name, 0, 0, 1, 1)
        grid.attach(self.entry_new_name, 1, 0, 2, 1)

        lbl_new_path = Gtk.Label(label="Neuer Pfad:")
        self.entry_new_path = Gtk.Entry()
        btn_browse = Gtk.Button(label="Durchsuchen")
        btn_browse.connect("clicked", self.on_browse)
        grid.attach(lbl_new_path, 0, 1, 1, 1)
        grid.attach(self.entry_new_path, 1, 1, 1, 1)
        grid.attach(btn_browse, 2, 1, 1, 1)

        box.add(grid)
        self.add_button("Abbrechen", Gtk.ResponseType.CANCEL)
        self.add_button("Klonen", Gtk.ResponseType.OK)
        self.show_all()

    def on_browse(self, widget):
        dialog = Gtk.FileChooserDialog(title="Zielordner auswählen", parent=self,
                                       action=Gtk.FileChooserAction.SELECT_FOLDER)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           "Auswählen", Gtk.ResponseType.OK)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.entry_new_path.set_text(dialog.get_filename())
        dialog.destroy()

    def get_clone_info(self):
        return {
            "new_name": self.entry_new_name.get_text(),
            "new_path": self.entry_new_path.get_text()
        }

# -------------------------------------------------------------------
# Hauptfenster der Anwendung
# -------------------------------------------------------------------
class QEMUManagerMain(Gtk.Window):
    def __init__(self):
        super().__init__(title="QEMU VM Manager")
        self.set_default_size(600, 400)
        self.vm_configs = load_all_vm_configs()
        self.build_ui()

    def build_ui(self):
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

        self.flow_box = Gtk.FlowBox()
        self.flow_box.set_max_children_per_line(1)
        self.flow_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow_box.set_halign(Gtk.Align.CENTER)
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self.flow_box)
        vbox.pack_start(scrolled, True, True, 0)
        self.add(vbox)
        self.refresh_vm_list()

    def on_add_vm(self, widget):
        iso_dialog = ISOSelectDialog(self)
        iso_dialog.show_all()

    def add_vm(self, vm_config):
        save_vm_config(vm_config)
        index = load_vm_index()
        if vm_config["path"] not in index:
            index.append(vm_config["path"])
            save_vm_index(index)
        self.vm_configs = load_all_vm_configs()
        self.refresh_vm_list()

    def refresh_vm_list(self):
        for child in self.flow_box.get_children():
            self.flow_box.remove(child)
        for vm in self.vm_configs:
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            hbox.set_hexpand(True)
            label_vm = Gtk.Label()
            label_vm.set_markup(f"<b><span foreground='white'>{vm['name']}</span></b>")
            label_vm.set_xalign(0)
            hbox.pack_start(label_vm, True, True, 0)
            btn_play = Gtk.Button(label="Start")
            btn_play.connect("clicked", lambda w, vm=vm: self.start_vm(vm))
            btn_settings = Gtk.Button(label="Einstellungen")
            btn_settings.connect("clicked", lambda w, vm=vm: self.edit_vm(vm))
            hbox.pack_end(btn_settings, False, False, 0)
            hbox.pack_end(btn_play, False, False, 0)
            event_box = Gtk.EventBox()
            event_box.add(hbox)
            event_box.connect("button-press-event", self.on_vm_event, vm)
            self.flow_box.add(event_box)
        self.flow_box.show_all()

    def on_vm_event(self, widget, event, vm):
        if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == 1:
            self.start_vm(vm)
        elif event.button == 3:
            menu = self.create_context_menu(vm)
            menu.popup_at_pointer(event)

    def create_context_menu(self, vm):
        menu = Gtk.Menu()
        item_start = Gtk.MenuItem(label="Start")
        item_start.connect("activate", lambda w: self.start_vm(vm))
        menu.append(item_start)
        item_shutdown = Gtk.MenuItem(label="Shutdown erzwingen")
        item_shutdown.connect("activate", lambda w: self.force_shutdown(vm))
        menu.append(item_shutdown)
        item_settings = Gtk.MenuItem(label="Einstellungen")
        item_settings.connect("activate", lambda w: self.edit_vm(vm))
        menu.append(item_settings)
        item_delete = Gtk.MenuItem(label="Löschen")
        item_delete.connect("activate", lambda w: self.delete_vm(vm))
        menu.append(item_delete)
        item_clone = Gtk.MenuItem(label="Klonen")
        item_clone.connect("activate", lambda w: self.clone_vm(vm))
        menu.append(item_clone)
        menu.show_all()
        return menu

    def start_vm(self, vm):
        print("Starte VM:", vm["name"])
        qemu_bin = shutil.which("qemu-kvm") or shutil.which("qemu-system-x86_64")
        if not qemu_bin:
            print("QEMU Binary nicht gefunden!")
            return

        disk_image = vm["disk_image"]
        if not os.path.exists(disk_image):
            qemu_img = shutil.which("qemu-img")
            if qemu_img:
                disk_size = vm["disk"]
                print("Erstelle Festplattenabbild:", disk_image)
                subprocess.call([qemu_img, "create", "-f", vm["disk_type"], disk_image, f"{disk_size}G"])
            else:
                print("qemu-img nicht gefunden! Kann Festplattenabbild nicht erstellen.")
                return

        cmd = [
            qemu_bin,
            "-enable-kvm",
            "-cpu", "host",
            "-smp", str(vm["cpu"]),
            "-m", str(vm["ram"]),
            "-drive", f"file={disk_image},format={vm['disk_type']},if=virtio",
            "-boot", "menu=on",
            "-usb",
            "-device", "usb-tablet",
            "-netdev", "user,id=net0",
            "-device", "virtio-net-pci,netdev=net0"
        ]
        display_mode = vm["display"].lower()
        if display_mode.startswith("gtk") or display_mode == "qxl":
            if vm.get("3d_acceleration", False):
                cmd.extend(["-vga", "qxl", "-display", "gtk,gl=on"])
            else:
                cmd.extend(["-vga", "qxl", "-display", "gtk"])
        elif display_mode == "spice":
            cmd.extend(["-vga", "qxl", "-display", "spice"])

        if vm.get("iso"):
            cmd.extend(["-cdrom", vm["iso"]])

        if vm.get("firmware") in ["UEFI", "UEFI+Secure Boot"]:
            secure = (vm["firmware"] == "UEFI+Secure Boot")
            ovmf_code, ovmf_vars = get_ovmf_files(secure=secure)
            if ovmf_code and ovmf_vars:
                cmd.extend([
                    "-drive", f"if=pflash,format=raw,readonly,file={ovmf_code}",
                    "-drive", f"if=pflash,format=raw,file={ovmf_vars}"
                ])
            else:
                print("UEFI Firmware Dateien nicht gefunden!")
                return

        print("Führe Befehl aus:", " ".join(cmd))
        subprocess.Popen(cmd)

    def force_shutdown(self, vm):
        print("Erzwinge Shutdown für VM:", vm["name"])
        # Hier kann z. B. über den QEMU-Monitor ein Shutdown-Befehl implementiert werden.

    def edit_vm(self, vm):
        settings_dialog = VMSettingsDialog(self, vm)
        response = settings_dialog.run()
        if response == Gtk.ResponseType.OK:
            updated = settings_dialog.get_updated_config()
            save_vm_config(updated)
            index = load_vm_index()
            if vm["path"] in index:
                index[index.index(vm["path"])] = updated["path"]
            save_vm_index(index)
            self.vm_configs = load_all_vm_configs()
            self.refresh_vm_list()
        settings_dialog.destroy()

    def delete_vm(self, vm):
        dialog = Gtk.MessageDialog(transient_for=self,
                                   message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.OK_CANCEL,
                                   text=f"Soll die VM '{vm['name']}' wirklich gelöscht werden?")
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            index = load_vm_index()
            if vm["path"] in index:
                index.remove(vm["path"])
                save_vm_index(index)
            self.vm_configs = [cfg for cfg in self.vm_configs if cfg["path"] != vm["path"]]
            self.refresh_vm_list()

    def clone_vm(self, vm):
        clone_dialog = VMCloneDialog(self, vm)
        response = clone_dialog.run()
        if response == Gtk.ResponseType.OK:
            clone_info = clone_dialog.get_clone_info()
            new_vm = vm.copy()
            new_vm["name"] = clone_info["new_name"]
            new_vm["path"] = clone_info["new_path"]
            new_vm["disk_image"] = os.path.join(new_vm["path"], new_vm["name"] + ".img")
            self.add_vm(new_vm)
        clone_dialog.destroy()

def main():
    win = QEMUManagerMain()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
