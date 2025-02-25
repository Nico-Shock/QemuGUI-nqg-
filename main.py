import os
import json
import shutil
import subprocess
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk

# Global base directory and index file for VM configurations.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = os.path.join(BASE_DIR, "vms_index.json")

# ------------------------------------------------------------
# Function to find OVMF (UEFI firmware) files from common paths.
# ------------------------------------------------------------
def find_ovmf_files():
    possible_dirs = ["/usr/share/OVMF", "/usr/local/share/OVMF", BASE_DIR]
    for d in possible_dirs:
        code = os.path.join(d, "OVMF_CODE.fd")
        vars = os.path.join(d, "OVMF_VARS.fd")
        if os.path.exists(code) and os.path.exists(vars):
            return code, vars
    return None, None

# ------------------------------------------------------------
# ISO Selection Window (via Drag & Drop or Plus button)
# ------------------------------------------------------------
class DragDropISOWindow(Gtk.Window):
    def __init__(self, parent):
        Gtk.Window.__init__(self, title="Select ISO")
        self.set_default_size(400, 300)
        self.parent = parent

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(20)
        vbox.set_margin_bottom(20)
        vbox.set_margin_start(20)
        vbox.set_margin_end(20)

        # Large plus button as clickable area
        plus_btn = Gtk.Button(label="+")
        plus_btn.set_size_request(100, 100)
        plus_btn.connect("clicked", self.open_file_dialog)
        vbox.pack_start(plus_btn, False, False, 0)

        # Drag & drop area
        drop_area = Gtk.EventBox()
        drop_area.set_size_request(300, 150)
        # Using deprecated override_background_color for simplicity
        drop_area.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.9, 0.9, 0.9, 1))
        drop_area.connect("drag-data-received", self.on_drag_data_received)
        drop_area.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        target = Gtk.TargetEntry.new("text/uri-list", 0, 0)
        drop_area.drag_dest_set_target_list(Gtk.TargetList.new([target]))
        vbox.pack_start(drop_area, True, True, 0)

        # Instruction text
        label = Gtk.Label(label="Drag & drop your ISO file here or click the plus button")
        vbox.pack_start(label, False, False, 0)

        self.add(vbox)

    def open_file_dialog(self, widget):
        dialog = Gtk.FileChooserDialog(title="Select ISO File", parent=self,
                                       action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        iso_filter = Gtk.FileFilter()
        iso_filter.set_name("ISO files")
        iso_filter.add_pattern("*.iso")
        dialog.add_filter(iso_filter)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            iso_path = dialog.get_filename()
            self.on_iso_selected(iso_path)
        dialog.destroy()

    def on_drag_data_received(self, widget, drag_context, x, y, data, info, time):
        uris = data.get_uris()
        if uris:
            iso_path = uris[0].replace("file://", "").strip()
            self.on_iso_selected(iso_path)

    def on_iso_selected(self, iso_path):
        # ISO selected – close window and open configuration dialog
        self.destroy()
        config_dialog = VMConfigDialog(self.parent, iso_path)
        response = config_dialog.run()
        if response == Gtk.ResponseType.OK:
            config = config_dialog.get_config()
            self.parent.add_vm(config)
        config_dialog.destroy()

# ------------------------------------------------------------
# Configuration Dialog for new VMs (full dialog)
# Only "QXL (3D accelerated)" and "Spice" are allowed as display options.
# ------------------------------------------------------------
class VMConfigDialog(Gtk.Dialog):
    def __init__(self, parent, iso_path=None, config=None):
        Gtk.Dialog.__init__(self, title="VM Configuration", transient_for=parent, flags=0)
        self.set_default_size(500, 400)
        self.iso_path = iso_path
        self.config = config or {}
        box = self.get_content_area()

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)

        lbl_name = Gtk.Label(label="VM Name:")
        self.entry_name = Gtk.Entry(text=self.config.get("name", ""))
        grid.attach(lbl_name, 0, 0, 1, 1)
        grid.attach(self.entry_name, 1, 0, 2, 1)

        lbl_path = Gtk.Label(label="VM Path:")
        self.entry_path = Gtk.Entry(text=self.config.get("path", BASE_DIR))
        btn_browse = Gtk.Button(label="Browse")
        btn_browse.connect("clicked", self.on_browse)
        grid.attach(lbl_path, 0, 1, 1, 1)
        grid.attach(self.entry_path, 1, 1, 1, 1)
        grid.attach(btn_browse, 2, 1, 1, 1)

        lbl_cpu = Gtk.Label(label="CPU Cores:")
        self.cpu_spin = Gtk.SpinButton.new_with_range(1, 32, 1)
        self.cpu_spin.set_value(self.config.get("cpu", 2))
        grid.attach(lbl_cpu, 0, 2, 1, 1)
        grid.attach(self.cpu_spin, 1, 2, 2, 1)

        lbl_ram = Gtk.Label(label="RAM (MiB):")
        self.ram_spin = Gtk.SpinButton.new_with_range(256, 131072, 256)
        self.ram_spin.set_value(self.config.get("ram", 4096))
        grid.attach(lbl_ram, 0, 3, 1, 1)
        grid.attach(self.ram_spin, 1, 3, 2, 1)

        lbl_disk = Gtk.Label(label="Disk Size (GB):")
        self.disk_spin = Gtk.SpinButton.new_with_range(1, 128, 1)
        self.disk_spin.set_value(self.config.get("disk", 40))
        grid.attach(lbl_disk, 0, 4, 1, 1)
        grid.attach(self.disk_spin, 1, 4, 2, 1)

        lbl_disk_type = Gtk.Label(label="Disk Type:")
        self.disk_qcow2 = Gtk.RadioButton.new_with_label_from_widget(None, "qcow2 (Recommended)")
        self.disk_raw = Gtk.RadioButton.new_with_label_from_widget(self.disk_qcow2, "raw (Full Disk)")
        grid.attach(lbl_disk_type, 0, 5, 1, 1)
        grid.attach(self.disk_qcow2, 1, 5, 1, 1)
        grid.attach(self.disk_raw, 2, 5, 1, 1)

        lbl_firmware = Gtk.Label(label="Firmware:")
        self.firmware_uefi = Gtk.RadioButton.new_with_label_from_widget(None, "UEFI")
        self.firmware_bios = Gtk.RadioButton.new_with_label_from_widget(self.firmware_uefi, "BIOS")
        grid.attach(lbl_firmware, 0, 6, 1, 1)
        grid.attach(self.firmware_uefi, 1, 6, 1, 1)
        grid.attach(self.firmware_bios, 2, 6, 1, 1)

        lbl_display = Gtk.Label(label="Display:")
        self.display_combo = Gtk.ComboBoxText()
        self.display_combo.append_text("QXL (3D accelerated)")
        self.display_combo.append_text("Spice")
        self.display_combo.set_active(0)
        grid.attach(lbl_display, 0, 7, 1, 1)
        grid.attach(self.display_combo, 1, 7, 2, 1)

        box.add(grid)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Create", Gtk.ResponseType.OK)
        self.show_all()

    def on_browse(self, widget):
        dialog = Gtk.FileChooserDialog(title="Select VM Directory", parent=self,
                                       action=Gtk.FileChooserAction.SELECT_FOLDER)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           "Select", Gtk.ResponseType.OK)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.entry_path.set_text(dialog.get_filename())
        dialog.destroy()

    def get_config(self):
        config = {
            "name": self.entry_name.get_text(),
            "path": self.entry_path.get_text(),
            "cpu": self.cpu_spin.get_value_as_int(),
            "ram": self.ram_spin.get_value_as_int(),  # in MiB
            "disk": self.disk_spin.get_value_as_int(),  # in GB
            "disk_type": "qcow2" if self.disk_qcow2.get_active() else "raw",
            "firmware": "UEFI" if self.firmware_uefi.get_active() else "BIOS",
            "display": self.display_combo.get_active_text(),
            "iso": self.iso_path
        }
        config["disk_image"] = os.path.join(config["path"], config["name"] + ".img")
        return config

# ------------------------------------------------------------
# Settings Dialog for editing an existing VM (only ISO, CPU, RAM, Firmware, Display)
# ------------------------------------------------------------
class VMSettingsDialog(Gtk.Dialog):
    def __init__(self, parent, config):
        Gtk.Dialog.__init__(self, title="Edit VM Settings", transient_for=parent, flags=0)
        self.set_default_size(500, 300)
        self.config = config.copy()
        box = self.get_content_area()

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)

        lbl_iso = Gtk.Label(label="ISO Path:")
        self.iso_entry = Gtk.Entry(text=self.config.get("iso", ""))
        grid.attach(lbl_iso, 0, 0, 1, 1)
        grid.attach(self.iso_entry, 1, 0, 2, 1)

        lbl_cpu = Gtk.Label(label="CPU Cores:")
        self.cpu_spin = Gtk.SpinButton.new_with_range(1, 32, 1)
        self.cpu_spin.set_value(self.config.get("cpu", 2))
        grid.attach(lbl_cpu, 0, 1, 1, 1)
        grid.attach(self.cpu_spin, 1, 1, 2, 1)

        lbl_ram = Gtk.Label(label="RAM (MiB):")
        self.ram_spin = Gtk.SpinButton.new_with_range(256, 131072, 256)
        self.ram_spin.set_value(self.config.get("ram", 4096))
        grid.attach(lbl_ram, 0, 2, 1, 1)
        grid.attach(self.ram_spin, 1, 2, 2, 1)

        lbl_firmware = Gtk.Label(label="Firmware:")
        self.firmware_uefi = Gtk.RadioButton.new_with_label_from_widget(None, "UEFI")
        self.firmware_bios = Gtk.RadioButton.new_with_label_from_widget(self.firmware_uefi, "BIOS")
        if self.config.get("firmware", "BIOS") == "UEFI":
            self.firmware_uefi.set_active(True)
        else:
            self.firmware_bios.set_active(True)
        grid.attach(lbl_firmware, 0, 3, 1, 1)
        grid.attach(self.firmware_uefi, 1, 3, 1, 1)
        grid.attach(self.firmware_bios, 2, 3, 1, 1)

        lbl_display = Gtk.Label(label="Display:")
        self.display_combo = Gtk.ComboBoxText()
        self.display_combo.append_text("QXL (3D accelerated)")
        self.display_combo.append_text("Spice")
        self.display_combo.set_active(0)
        grid.attach(lbl_display, 0, 4, 1, 1)
        grid.attach(self.display_combo, 1, 4, 2, 1)

        box.add(grid)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Save", Gtk.ResponseType.OK)
        self.show_all()

    def get_config(self):
        self.config["iso"] = self.iso_entry.get_text()
        self.config["cpu"] = self.cpu_spin.get_value_as_int()
        self.config["ram"] = self.ram_spin.get_value_as_int()
        self.config["firmware"] = "UEFI" if self.firmware_uefi.get_active() else "BIOS"
        self.config["display"] = self.display_combo.get_active_text()
        return self.config

# ------------------------------------------------------------
# Global functions for handling per-VM configuration files.
# The global index (vms_index.json) in BASE_DIR stores a list of VM paths.
# Each VM's configuration is stored as "vm_config.json" in its own folder.
# ------------------------------------------------------------
def load_vm_index():
    index_file = os.path.join(BASE_DIR, "vms_index.json")
    if os.path.exists(index_file) and os.path.getsize(index_file) > 0:
        try:
            with open(index_file, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

def save_vm_index(index):
    index_file = os.path.join(BASE_DIR, "vms_index.json")
    with open(index_file, "w") as f:
        json.dump(index, f, indent=4)

def load_all_vm_configs():
    index = load_vm_index()
    configs = []
    for vm_path in index:
        config_file = os.path.join(vm_path, "vm_config.json")
        if os.path.exists(config_file):
            try:
                with open(config_file, "r") as f:
                    config = json.load(f)
                    configs.append(config)
            except json.JSONDecodeError:
                continue
    return configs

def save_vm_config(config):
    config_file = os.path.join(config["path"], "vm_config.json")
    with open(config_file, "w") as f:
        json.dump(config, f, indent=4)

# ------------------------------------------------------------
# Main Window: List view (vertical list, horizontally centered)
# A double-click starts the VM; right-click opens the context menu.
# ------------------------------------------------------------
class MainWindow(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, title="QEMU Manager")
        self.set_default_size(600, 400)
        self.vm_configs = load_all_vm_configs()
        self.init_ui()

    def init_ui(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.set_margin_top(10)
        vbox.set_margin_bottom(10)
        vbox.set_margin_start(10)
        vbox.set_margin_end(10)

        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        self.set_titlebar(header)
        self.add_btn = Gtk.Button(label="+")
        self.add_btn.connect("clicked", self.on_add_vm)
        header.pack_end(self.add_btn)

        self.flowbox = Gtk.FlowBox()
        self.flowbox.set_max_children_per_line(1)
        self.flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flowbox.set_halign(Gtk.Align.CENTER)
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self.flowbox)
        vbox.pack_start(scrolled, True, True, 0)
        self.add(vbox)
        self.refresh_vm_list()

    def on_add_vm(self, widget):
        iso_window = DragDropISOWindow(self)
        iso_window.show_all()

    def add_vm(self, config):
        save_vm_config(config)
        index = load_vm_index()
        if config["path"] not in index:
            index.append(config["path"])
            save_vm_index(index)
        self.vm_configs = load_all_vm_configs()
        self.refresh_vm_list()

    def refresh_vm_list(self):
        for child in self.flowbox.get_children():
            self.flowbox.remove(child)
        for vm in self.vm_configs:
            frame = Gtk.Frame()
            frame.set_size_request(200, -1)
            frame.get_style_context().add_class("vm-frame")
            frame.set_halign(Gtk.Align.CENTER)
            label = Gtk.Label(label=vm["name"])
            label.get_style_context().add_class("vm-label")
            label.set_halign(Gtk.Align.CENTER)
            label.set_valign(Gtk.Align.CENTER)
            event_box = Gtk.EventBox()
            event_box.add(label)
            event_box.connect("button-press-event", self.on_vm_event, vm)
            frame.add(event_box)
            self.flowbox.add(frame)
        self.flowbox.show_all()

    def on_vm_event(self, widget, event, vm):
        if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == 1:
            self.start_vm(vm)
        elif event.button == 3:
            menu = self.create_context_menu(vm)
            menu.popup_at_pointer(event)

    def create_context_menu(self, vm):
        menu = Gtk.Menu()
        start_item = Gtk.MenuItem(label="Start")
        start_item.connect("activate", lambda w: self.start_vm(vm))
        menu.append(start_item)
        shutdown_item = Gtk.MenuItem(label="Force Shutdown")
        shutdown_item.connect("activate", lambda w: self.force_shutdown(vm))
        menu.append(shutdown_item)
        settings_item = Gtk.MenuItem(label="Settings")
        settings_item.connect("activate", lambda w: self.edit_vm(vm))
        menu.append(settings_item)
        delete_item = Gtk.MenuItem(label="Delete")
        delete_item.connect("activate", lambda w: self.delete_vm(vm))
        menu.append(delete_item)
        clone_item = Gtk.MenuItem(label="Clone")
        clone_item.connect("activate", lambda w: self.clone_vm(vm))
        menu.append(clone_item)
        menu.show_all()
        return menu

    def start_vm(self, vm):
        print("Starting VM:", vm["name"])
        qemu_bin = shutil.which("qemu-kvm") or shutil.which("qemu-system-x86_64")
        if not qemu_bin:
            print("QEMU binary not found!")
            return

        disk_image = vm["disk_image"]
        if not os.path.exists(disk_image):
            qemu_img = shutil.which("qemu-img")
            if qemu_img:
                disk_size = vm["disk"]  # in GB
                print("Creating disk image:", disk_image)
                subprocess.call([qemu_img, "create", "-f", "qcow2", disk_image, f"{disk_size}G"])
            else:
                print("qemu-img binary not found! Cannot create disk image.")
                return

        # Build QEMU command with additional parameters.
        cmd = [
            qemu_bin,
            "-enable-kvm",
            "-cpu", "host",
            "-smp", str(vm["cpu"]),
            "-m", str(vm["ram"]),
            "-drive", f"file={disk_image},format=qcow2,if=virtio",
            "-boot", "menu=on",
            "-usb",
            "-device", "usb-tablet",
            "-netdev", "user,id=net0",
            "-device", "virtio-net-pci,netdev=net0"
        ]
        # Set display and VGA options based on selection.
        if vm["display"] == "QXL (3D accelerated)":
            cmd.extend(["-vga", "qxl", "-display", "gtk,gl=on"])
        elif vm["display"] == "Spice":
            cmd.extend(["-vga", "qxl", "-display", "spice"])

        # Attach the ISO as a CD-ROM.
        if vm.get("iso"):
            cmd.extend(["-cdrom", vm["iso"]])
        # If UEFI is selected, use OVMF files found dynamically.
        if vm.get("firmware") == "UEFI":
            ovmf_code, ovmf_vars = find_ovmf_files()
            if ovmf_code and ovmf_vars:
                cmd.extend([
                    "-drive", f"if=pflash,format=raw,readonly,file={ovmf_code}",
                    "-drive", f"if=pflash,format=raw,file={ovmf_vars}"
                ])
            else:
                print("UEFI firmware files not found!")
                return

        print("Executing command:", " ".join(cmd))
        subprocess.Popen(cmd)

    def force_shutdown(self, vm):
        print("Force shutting down VM:", vm["name"])
        # Implement shutdown mechanism via QEMU Monitor if needed.

    def edit_vm(self, vm):
        settings_dialog = VMSettingsDialog(self, vm)
        response = settings_dialog.run()
        if response == Gtk.ResponseType.OK:
            updated_config = settings_dialog.get_config()
            save_vm_config(updated_config)
            index = load_vm_index()
            if vm["path"] in index:
                # Replace old config with updated one.
                index[index.index(vm["path"])] = updated_config["path"]
            save_vm_index(index)
            self.vm_configs = load_all_vm_configs()
            self.refresh_vm_list()
        settings_dialog.destroy()

    def delete_vm(self, vm):
        dialog = Gtk.MessageDialog(transient_for=self,
                                   message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.OK_CANCEL,
                                   text=f"Are you sure you want to delete VM '{vm['name']}'?")
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
        dialog = Gtk.FileChooserDialog(title="Select Clone Destination Folder", parent=self,
                                       action=Gtk.FileChooserAction.SELECT_FOLDER)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           "Clone", Gtk.ResponseType.OK)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            dest_path = dialog.get_filename()
            new_vm = vm.copy()
            base_name = vm["name"]
            count = 1
            new_name = f"{base_name}_{count}"
            while any(v["name"] == new_name for v in self.vm_configs):
                count += 1
                new_name = f"{base_name}_{count}"
            new_vm["name"] = new_name
            new_vm["path"] = dest_path
            new_vm["disk_image"] = os.path.join(dest_path, new_name + ".img")
            self.add_vm(new_vm)
        dialog.destroy()

    def load_config(self):
        # Load all VM configs from their individual vm_config.json files using the global index.
        configs = []
        index = load_vm_index()
        for vm_path in index:
            config_file = os.path.join(vm_path, "vm_config.json")
            if os.path.exists(config_file):
                try:
                    with open(config_file, "r") as f:
                        cfg = json.load(f)
                        configs.append(cfg)
                except json.JSONDecodeError:
                    continue
        return configs

    def save_config(self):
        # Not used globally; each VM config is saved individually.
        pass

class VMSettingsDialog(Gtk.Dialog):
    def __init__(self, parent, config):
        Gtk.Dialog.__init__(self, title="Edit VM Settings", transient_for=parent, flags=0)
        self.set_default_size(500, 300)
        self.config = config.copy()
        box = self.get_content_area()

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)

        lbl_iso = Gtk.Label(label="ISO Path:")
        self.iso_entry = Gtk.Entry(text=self.config.get("iso", ""))
        grid.attach(lbl_iso, 0, 0, 1, 1)
        grid.attach(self.iso_entry, 1, 0, 2, 1)

        lbl_cpu = Gtk.Label(label="CPU Cores:")
        self.cpu_spin = Gtk.SpinButton.new_with_range(1, 32, 1)
        self.cpu_spin.set_value(self.config.get("cpu", 2))
        grid.attach(lbl_cpu, 0, 1, 1, 1)
        grid.attach(self.cpu_spin, 1, 1, 2, 1)

        lbl_ram = Gtk.Label(label="RAM (MiB):")
        self.ram_spin = Gtk.SpinButton.new_with_range(256, 131072, 256)
        self.ram_spin.set_value(self.config.get("ram", 4096))
        grid.attach(lbl_ram, 0, 2, 1, 1)
        grid.attach(self.ram_spin, 1, 2, 2, 1)

        lbl_firmware = Gtk.Label(label="Firmware:")
        self.firmware_uefi = Gtk.RadioButton.new_with_label_from_widget(None, "UEFI")
        self.firmware_bios = Gtk.RadioButton.new_with_label_from_widget(self.firmware_uefi, "BIOS")
        if self.config.get("firmware", "BIOS") == "UEFI":
            self.firmware_uefi.set_active(True)
        else:
            self.firmware_bios.set_active(True)
        grid.attach(lbl_firmware, 0, 3, 1, 1)
        grid.attach(self.firmware_uefi, 1, 3, 1, 1)
        grid.attach(self.firmware_bios, 2, 3, 1, 1)

        lbl_display = Gtk.Label(label="Display:")
        self.display_combo = Gtk.ComboBoxText()
        self.display_combo.append_text("QXL (3D accelerated)")
        self.display_combo.append_text("Spice")
        self.display_combo.set_active(0)
        grid.attach(lbl_display, 0, 4, 1, 1)
        grid.attach(self.display_combo, 1, 4, 2, 1)

        box.add(grid)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Save", Gtk.ResponseType.OK)
        self.show_all()

    def get_config(self):
        self.config["iso"] = self.iso_entry.get_text()
        self.config["cpu"] = self.cpu_spin.get_value_as_int()
        self.config["ram"] = self.ram_spin.get_value_as_int()
        self.config["firmware"] = "UEFI" if self.firmware_uefi.get_active() else "BIOS"
        self.config["display"] = self.display_combo.get_active_text()
        return self.config

# ------------------------------------------------------------
# Global functions for VM configuration handling.
# Each VM's config is stored in its own folder as "vm_config.json".
# The global index file "vms_index.json" in BASE_DIR stores a list of VM paths.
# ------------------------------------------------------------
def load_vm_index():
    index_file = os.path.join(BASE_DIR, "vms_index.json")
    if os.path.exists(index_file) and os.path.getsize(index_file) > 0:
        try:
            with open(index_file, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

def save_vm_index(index):
    index_file = os.path.join(BASE_DIR, "vms_index.json")
    with open(index_file, "w") as f:
        json.dump(index, f, indent=4)

def load_all_vm_configs():
    index = load_vm_index()
    configs = []
    for vm_path in index:
        config_file = os.path.join(vm_path, "vm_config.json")
        if os.path.exists(config_file):
            try:
                with open(config_file, "r") as f:
                    config = json.load(f)
                    configs.append(config)
            except json.JSONDecodeError:
                continue
    return configs

def save_vm_config(config):
    config_file = os.path.join(config["path"], "vm_config.json")
    with open(config_file, "w") as f:
        json.dump(config, f, indent=4)

# ------------------------------------------------------------
# Main Window: List view (vertical list, horizontally centered)
# A double-click starts the VM; right-click opens the context menu.
# ------------------------------------------------------------
class MainWindow(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, title="QEMU Manager")
        self.set_default_size(600, 400)
        self.vm_configs = load_all_vm_configs()
        self.init_ui()

    def init_ui(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.set_margin_top(10)
        vbox.set_margin_bottom(10)
        vbox.set_margin_start(10)
        vbox.set_margin_end(10)

        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        self.set_titlebar(header)
        self.add_btn = Gtk.Button(label="+")
        self.add_btn.connect("clicked", self.on_add_vm)
        header.pack_end(self.add_btn)

        self.flowbox = Gtk.FlowBox()
        self.flowbox.set_max_children_per_line(1)
        self.flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flowbox.set_halign(Gtk.Align.CENTER)
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self.flowbox)
        vbox.pack_start(scrolled, True, True, 0)
        self.add(vbox)
        self.refresh_vm_list()

    def on_add_vm(self, widget):
        iso_window = DragDropISOWindow(self)
        iso_window.show_all()

    def add_vm(self, config):
        save_vm_config(config)
        index = load_vm_index()
        if config["path"] not in index:
            index.append(config["path"])
            save_vm_index(index)
        self.vm_configs = load_all_vm_configs()
        self.refresh_vm_list()

    def refresh_vm_list(self):
        for child in self.flowbox.get_children():
            self.flowbox.remove(child)
        for vm in self.vm_configs:
            frame = Gtk.Frame()
            frame.set_size_request(200, -1)
            frame.get_style_context().add_class("vm-frame")
            frame.set_halign(Gtk.Align.CENTER)
            label = Gtk.Label(label=vm["name"])
            label.get_style_context().add_class("vm-label")
            label.set_halign(Gtk.Align.CENTER)
            label.set_valign(Gtk.Align.CENTER)
            event_box = Gtk.EventBox()
            event_box.add(label)
            event_box.connect("button-press-event", self.on_vm_event, vm)
            frame.add(event_box)
            self.flowbox.add(frame)
        self.flowbox.show_all()

    def on_vm_event(self, widget, event, vm):
        if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == 1:
            self.start_vm(vm)
        elif event.button == 3:
            menu = self.create_context_menu(vm)
            menu.popup_at_pointer(event)

    def create_context_menu(self, vm):
        menu = Gtk.Menu()
        start_item = Gtk.MenuItem(label="Start")
        start_item.connect("activate", lambda w: self.start_vm(vm))
        menu.append(start_item)
        shutdown_item = Gtk.MenuItem(label="Force Shutdown")
        shutdown_item.connect("activate", lambda w: self.force_shutdown(vm))
        menu.append(shutdown_item)
        settings_item = Gtk.MenuItem(label="Settings")
        settings_item.connect("activate", lambda w: self.edit_vm(vm))
        menu.append(settings_item)
        delete_item = Gtk.MenuItem(label="Delete")
        delete_item.connect("activate", lambda w: self.delete_vm(vm))
        menu.append(delete_item)
        clone_item = Gtk.MenuItem(label="Clone")
        clone_item.connect("activate", lambda w: self.clone_vm(vm))
        menu.append(clone_item)
        menu.show_all()
        return menu

    def start_vm(self, vm):
        print("Starting VM:", vm["name"])
        qemu_bin = shutil.which("qemu-kvm") or shutil.which("qemu-system-x86_64")
        if not qemu_bin:
            print("QEMU binary not found!")
            return

        disk_image = vm["disk_image"]
        if not os.path.exists(disk_image):
            qemu_img = shutil.which("qemu-img")
            if qemu_img:
                disk_size = vm["disk"]  # in GB
                print("Creating disk image:", disk_image)
                subprocess.call([qemu_img, "create", "-f", "qcow2", disk_image, f"{disk_size}G"])
            else:
                print("qemu-img binary not found! Cannot create disk image.")
                return

        cmd = [
            qemu_bin,
            "-enable-kvm",
            "-cpu", "host",
            "-smp", str(vm["cpu"]),
            "-m", str(vm["ram"]),
            "-drive", f"file={disk_image},format=qcow2,if=virtio",
            "-boot", "menu=on",
            "-usb",
            "-device", "usb-tablet",
            "-netdev", "user,id=net0",
            "-device", "virtio-net-pci,netdev=net0"
        ]
        if vm["display"] == "QXL (3D accelerated)":
            cmd.extend(["-vga", "qxl", "-display", "gtk,gl=on"])
        elif vm["display"] == "Spice":
            cmd.extend(["-vga", "qxl", "-display", "spice"])

        if vm.get("iso"):
            cmd.extend(["-cdrom", vm["iso"]])

        if vm.get("firmware") == "UEFI":
            ovmf_code, ovmf_vars = find_ovmf_files()
            if ovmf_code and ovmf_vars:
                cmd.extend([
                    "-drive", f"if=pflash,format=raw,readonly,file={ovmf_code}",
                    "-drive", f"if=pflash,format=raw,file={ovmf_vars}"
                ])
            else:
                print("UEFI firmware files not found!")
                return

        print("Executing command:", " ".join(cmd))
        subprocess.Popen(cmd)

    def force_shutdown(self, vm):
        print("Force shutting down VM:", vm["name"])
        # Implement a shutdown mechanism via QEMU Monitor if needed.

    def edit_vm(self, vm):
        settings_dialog = VMSettingsDialog(self, vm)
        response = settings_dialog.run()
        if response == Gtk.ResponseType.OK:
            updated_config = settings_dialog.get_config()
            save_vm_config(updated_config)
            index = load_vm_index()
            if vm["path"] in index:
                # Replace old config with updated one.
                index[index.index(vm["path"])] = updated_config["path"]
            save_vm_index(index)
            self.vm_configs = load_all_vm_configs()
            self.refresh_vm_list()
        settings_dialog.destroy()

    def delete_vm(self, vm):
        dialog = Gtk.MessageDialog(transient_for=self,
                                   message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.OK_CANCEL,
                                   text=f"Are you sure you want to delete VM '{vm['name']}'?")
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
        dialog = Gtk.FileChooserDialog(title="Select Clone Destination Folder", parent=self,
                                       action=Gtk.FileChooserAction.SELECT_FOLDER)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           "Clone", Gtk.ResponseType.OK)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            dest_path = dialog.get_filename()
            new_vm = vm.copy()
            base_name = vm["name"]
            count = 1
            new_name = f"{base_name}_{count}"
            while any(v["name"] == new_name for v in self.vm_configs):
                count += 1
                new_name = f"{base_name}_{count}"
            new_vm["name"] = new_name
            new_vm["path"] = dest_path
            new_vm["disk_image"] = os.path.join(dest_path, new_name + ".img")
            self.add_vm(new_vm)
        dialog.destroy()

    def load_config(self):
        configs = []
        index = load_vm_index()
        for vm_path in index:
            config_file = os.path.join(vm_path, "vm_config.json")
            if os.path.exists(config_file):
                try:
                    with open(config_file, "r") as f:
                        config = json.load(f)
                        configs.append(config)
                except json.JSONDecodeError:
                    continue
        return configs

    def save_config(self):
        # Not used globally; each VM config is saved individually.
        pass

class VMSettingsDialog(Gtk.Dialog):
    def __init__(self, parent, config):
        Gtk.Dialog.__init__(self, title="Edit VM Settings", transient_for=parent, flags=0)
        self.set_default_size(500, 300)
        self.config = config.copy()
        box = self.get_content_area()

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)

        lbl_iso = Gtk.Label(label="ISO Path:")
        self.iso_entry = Gtk.Entry(text=self.config.get("iso", ""))
        grid.attach(lbl_iso, 0, 0, 1, 1)
        grid.attach(self.iso_entry, 1, 0, 2, 1)

        lbl_cpu = Gtk.Label(label="CPU Cores:")
        self.cpu_spin = Gtk.SpinButton.new_with_range(1, 32, 1)
        self.cpu_spin.set_value(self.config.get("cpu", 2))
        grid.attach(lbl_cpu, 0, 1, 1, 1)
        grid.attach(self.cpu_spin, 1, 1, 2, 1)

        lbl_ram = Gtk.Label(label="RAM (MiB):")
        self.ram_spin = Gtk.SpinButton.new_with_range(256, 131072, 256)
        self.ram_spin.set_value(self.config.get("ram", 4096))
        grid.attach(lbl_ram, 0, 2, 1, 1)
        grid.attach(self.ram_spin, 1, 2, 2, 1)

        lbl_firmware = Gtk.Label(label="Firmware:")
        self.firmware_uefi = Gtk.RadioButton.new_with_label_from_widget(None, "UEFI")
        self.firmware_bios = Gtk.RadioButton.new_with_label_from_widget(self.firmware_uefi, "BIOS")
        if self.config.get("firmware", "BIOS") == "UEFI":
            self.firmware_uefi.set_active(True)
        else:
            self.firmware_bios.set_active(True)
        grid.attach(lbl_firmware, 0, 3, 1, 1)
        grid.attach(self.firmware_uefi, 1, 3, 1, 1)
        grid.attach(self.firmware_bios, 2, 3, 1, 1)

        lbl_display = Gtk.Label(label="Display:")
        self.display_combo = Gtk.ComboBoxText()
        self.display_combo.append_text("QXL (3D accelerated)")
        self.display_combo.append_text("Spice")
        self.display_combo.set_active(0)
        grid.attach(lbl_display, 0, 4, 1, 1)
        grid.attach(self.display_combo, 1, 4, 2, 1)

        box.add(grid)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Save", Gtk.ResponseType.OK)
        self.show_all()

    def get_config(self):
        self.config["iso"] = self.iso_entry.get_text()
        self.config["cpu"] = self.cpu_spin.get_value_as_int()
        self.config["ram"] = self.ram_spin.get_value_as_int()
        self.config["firmware"] = "UEFI" if self.firmware_uefi.get_active() else "BIOS"
        self.config["display"] = self.display_combo.get_active_text()
        return self.config

def main():
    win = MainWindow()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
