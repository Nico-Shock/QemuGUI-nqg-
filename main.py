#!/usr/bin/env python3
import os, json, subprocess, shutil, threading, urllib.parse
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib

# ===== GLOBAL CONFIG =====
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".qemu_manager")
if not os.path.exists(CONFIG_DIR):
    os.makedirs(CONFIG_DIR)
INDEX_FILE = os.path.join(CONFIG_DIR, "vms_index.json")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ===== OVMF FILES =====
def get_ovmf_files(secure=False, custom_dir=None):
    dirs = []
    if custom_dir:
        dirs.append(custom_dir)
    dirs.extend(["/usr/share/OVMF", "/usr/local/share/OVMF", BASE_DIR])
    for d in dirs:
        code = os.path.join(d, "OVMF_CODE.secboot.4m.fd" if secure else "OVMF_CODE.4m.fd")
        vars_file = os.path.join(d, "OVMF_VARS.fd")
        if os.path.exists(code) and os.path.exists(vars_file):
            return code, vars_file
    return "", ""

def copy_uefi_files(config):
    ovmf_dir = os.path.join(config["path"], "ovmf")
    secure = (config["firmware"] == "UEFI+Secure Boot")
    os.makedirs(ovmf_dir, exist_ok=True)
    try:
        src_code = "/usr/share/edk2/x64/OVMF_CODE.secboot.4m.fd" if secure else "/usr/share/edk2/x64/OVMF_CODE.4m.fd"
        src_vars = "/usr/share/edk2/x64/OVMF_VARS.fd"
        shutil.copy(src_code, os.path.join(ovmf_dir, os.path.basename(src_code)))
        shutil.copy(src_vars, os.path.join(ovmf_dir, os.path.basename(src_vars)))
    except Exception:
        show_error_dialog("Failed to copy UEFI firmware files!")
    code, vars_file = get_ovmf_files(secure, custom_dir=ovmf_dir)
    config["ovmf_code"] = code
    config["ovmf_vars"] = vars_file

def build_launch_command(config):
    qemu = shutil.which("qemu-kvm") or shutil.which("qemu-system-x86_64")
    if not qemu:
        return None
    cmd = [qemu, "-enable-kvm", "-cpu", "host",
           "-smp", str(config["cpu"]),
           "-m", str(config["ram"]),
           "-drive", f"file={config['disk_image']},format={config['disk_type']},if=virtio",
           "-boot", "menu=on",
           "-usb", "-device", "usb-tablet",
           "-netdev", "user,id=net0", "-device", "virtio-net-pci,netdev=net0"]
    dmode = config["display"].lower()
    if dmode.startswith("gtk") or dmode == "qxl":
        if config.get("3d_acceleration", False):
            cmd.extend(["-vga", "qxl", "-display", "gtk,gl=on"])
        else:
            cmd.extend(["-vga", "qxl", "-display", "gtk"])
    elif dmode == "spice":
        cmd.extend(["-vga", "qxl", "-display", "spice"])
    if config.get("iso"):
        iso_path = urllib.parse.unquote(config["iso"])
        cmd.extend(["-cdrom", iso_path])
    if config.get("firmware") in ["UEFI", "UEFI+Secure Boot"]:
        if config.get("ovmf_code"):
            cmd.extend(["-bios", config["ovmf_code"]])
    return cmd

def load_vm_index():
    if os.path.exists(INDEX_FILE) and os.path.getsize(INDEX_FILE) > 0:
        try:
            with open(INDEX_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_vm_index(index):
    with open(INDEX_FILE, "w") as f:
        json.dump(index, f, indent=4)

def load_all_vm_configs():
    index = load_vm_index()
    configs = []
    for vm_path in index:
        try:
            for fname in os.listdir(vm_path):
                if fname.endswith(".conf"):
                    with open(os.path.join(vm_path, fname), "r") as f:
                        configs.append(json.load(f))
                    break
        except Exception as e:
            print("Error loading config from", vm_path, e)
    return configs

def save_vm_config(config):
    conf_file = os.path.join(config["path"], f"{config['name']}.conf")
    try:
        with open(conf_file, "w") as f:
            json.dump(config, f, indent=4)
    except Exception:
        show_error_dialog("Error saving VM configuration.\nCheck your permissions.")
        raise

def show_error_dialog(msg):
    d = Gtk.MessageDialog(transient_for=None, flags=0,
                          message_type=Gtk.MessageType.ERROR,
                          buttons=Gtk.ButtonsType.OK, text=msg)
    d.run()
    d.destroy()

class LoadingDialog(Gtk.Dialog):
    def __init__(self, parent, msg="Installing OVMF firmware files..."):
        super().__init__(title="Please wait", transient_for=parent)
        self.set_modal(True)
        self.set_default_size(300, 100)
        box = self.get_content_area()
        box.add(Gtk.Label(label=msg))
        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(False)
        box.add(self.progress)
        self.show_all()
        self.timeout_id = GLib.timeout_add(100, self.on_timeout)
    def on_timeout(self):
        self.progress.pulse()
        return True
    def destroy(self):
        GLib.source_remove(self.timeout_id)
        super().destroy()

class ISOSelectDialog(Gtk.Window):
    def __init__(self, parent):
        super().__init__(title="Select ISO")
        self.parent = parent
        self.set_default_size(400,300)
        self.set_position(Gtk.WindowPosition.CENTER)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(20); vbox.set_margin_bottom(20)
        vbox.set_margin_start(20); vbox.set_margin_end(20)
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
        vbox.pack_start(Gtk.Label(label="Drag and drop your ISO file here or click '+'"), False, False, 0)
        self.add(vbox)
    def on_plus_clicked(self, w):
        d = Gtk.FileChooserDialog(title="Select ISO File", parent=self,
                                  action=Gtk.FileChooserAction.OPEN)
        d.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        f = Gtk.FileFilter(); f.set_name("ISO files"); f.add_pattern("*.iso"); d.add_filter(f)
        if d.run() == Gtk.ResponseType.OK:
            self.iso_chosen(d.get_filename())
        d.destroy()
    def on_drag_received(self, w, dc, x, y, data, info, time):
        uris = data.get_uris()
        if uris:
            self.iso_chosen(uris[0].replace("file://", "").strip())
    def iso_chosen(self, iso_path):
        self.destroy()
        d = VMCreateDialog(self.parent, iso_path)
        if d.run() == Gtk.ResponseType.OK:
            self.parent.add_vm(d.get_vm_config())
        d.destroy()

class VMCreateDialog(Gtk.Dialog):
    def __init__(self, parent, iso_path=None):
        super().__init__(title="New VM Configuration", transient_for=parent)
        self.set_default_size(500,500)
        self.iso_path = iso_path
        box = self.get_content_area()
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_margin_top(10); grid.set_margin_bottom(10)
        grid.set_margin_start(10); grid.set_margin_end(10)
        grid.attach(Gtk.Label(label="VM Name:"), 0, 0, 1, 1)
        self.entry_name = Gtk.Entry()
        grid.attach(self.entry_name, 1, 0, 2, 1)
        grid.attach(Gtk.Label(label="VM Directory:"), 0, 1, 1, 1)
        self.entry_path = Gtk.Entry()
        btn = Gtk.Button(label="Browse")
        btn.connect("clicked", self.on_browse)
        grid.attach(self.entry_path, 1, 1, 1, 1)
        grid.attach(btn, 2, 1, 1, 1)
        grid.attach(Gtk.Label(label="CPU Cores:"), 0, 2, 1, 1)
        self.spin_cpu = Gtk.SpinButton.new_with_range(1, 32, 1)
        self.spin_cpu.set_value(2)
        grid.attach(self.spin_cpu, 1, 2, 2, 1)
        grid.attach(Gtk.Label(label="RAM (MiB):"), 0, 3, 1, 1)
        self.spin_ram = Gtk.SpinButton.new_with_range(256, 131072, 256)
        self.spin_ram.set_value(4096)
        grid.attach(self.spin_ram, 1, 3, 2, 1)
        grid.attach(Gtk.Label(label="Disk Size (GB):"), 0, 4, 1, 1)
        self.spin_disk = Gtk.SpinButton.new_with_range(1, 128, 1)
        self.spin_disk.set_value(40)
        grid.attach(self.spin_disk, 1, 4, 2, 1)
        grid.attach(Gtk.Label(label="Disk Type:"), 0, 5, 1, 1)
        self.radio_qcow2 = Gtk.RadioButton.new_with_label_from_widget(None, "qcow2 (Recommended)")
        self.radio_raw = Gtk.RadioButton.new_with_label_from_widget(self.radio_qcow2, "raw (Full)")
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
        grid.attach(Gtk.Label(label="Display:"), 0, 7, 1, 1)
        self.combo_disp = Gtk.ComboBoxText()
        for opt in ["gtk (default)", "qxl", "spice"]:
            self.combo_disp.append_text(opt)
        self.combo_disp.set_active(0)
        grid.attach(self.combo_disp, 1, 7, 2, 1)
        grid.attach(Gtk.Label(label="3D Acceleration:"), 0, 8, 1, 1)
        self.check_3d = Gtk.CheckButton()
        grid.attach(self.check_3d, 1, 8, 2, 1)
        box.add(grid)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Create", Gtk.ResponseType.OK)
        self.show_all()
    def on_browse(self, w):
        d = Gtk.FileChooserDialog(title="Select VM Directory", parent=self,
                                  action=Gtk.FileChooserAction.SELECT_FOLDER)
        d.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Select", Gtk.ResponseType.OK)
        if d.run() == Gtk.ResponseType.OK:
            self.entry_path.set_text(d.get_filename())
        d.destroy()
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
            "iso": urllib.parse.unquote(self.iso_path) if self.iso_path else "",
            "3d_acceleration": self.check_3d.get_active(),
            "disk_image": os.path.join(self.entry_path.get_text(), self.entry_name.get_text() + ".img")
        }
        if not os.path.exists(config["disk_image"]):
            qemu_img = shutil.which("qemu-img")
            if qemu_img:
                try:
                    subprocess.check_call([qemu_img, "create", "-f", config["disk_type"],
                                           config["disk_image"], f"{config['disk']}G"])
                except Exception:
                    pass
        if config["firmware"] in ["UEFI", "UEFI+Secure Boot"]:
            ovmf_dir = os.path.join(config["path"], "ovmf")
            secure = (config["firmware"] == "UEFI+Secure Boot")
            os.makedirs(ovmf_dir, exist_ok=True)
            code, vars_file = get_ovmf_files(secure, custom_dir=ovmf_dir)
            if not (code and vars_file):
                pkg_cmd = None
                if shutil.which("apt-get"):
                    pkg_cmd = ["apt-get", "install", "-y", "ovmf"]
                elif shutil.which("dnf"):
                    pkg_cmd = ["dnf", "install", "-y", "edk2-ovmf"]
                elif shutil.which("pacman"):
                    pkg_cmd = ["pacman", "-S", "--noconfirm", "edk2-ovmf"]
                if pkg_cmd is not None:
                    sudo_pwd = prompt_sudo_password(None)
                    if sudo_pwd is None:
                        show_error_dialog("Sudo password not provided!")
                    else:
                        full_cmd = f"echo {sudo_pwd} | sudo -S " + " ".join(pkg_cmd)
                        try:
                            subprocess.check_call(full_cmd, shell=True)
                        except Exception:
                            pass
                    try:
                        src_code = "/usr/share/edk2/x64/OVMF_CODE.secboot.4m.fd" if secure else "/usr/share/edk2/x64/OVMF_CODE.4m.fd"
                        src_vars = "/usr/share/edk2/x64/OVMF_VARS.fd"
                        shutil.copy(src_code, os.path.join(ovmf_dir, os.path.basename(src_code)))
                        shutil.copy(src_vars, os.path.join(ovmf_dir, os.path.basename(src_vars)))
                    except Exception:
                        pass
                    code, vars_file = get_ovmf_files(secure, custom_dir=ovmf_dir)
            config["ovmf_code"] = code
            config["ovmf_vars"] = vars_file
        config["launch_cmd"] = build_launch_command(config)
        return config

def prompt_sudo_password(parent):
    d = Gtk.Dialog(title="Sudo Password Required", transient_for=parent, flags=0)
    d.add_buttons("OK", Gtk.ResponseType.OK, "Cancel", Gtk.ResponseType.CANCEL)
    box = d.get_content_area()
    box.add(Gtk.Label(label="Enter your sudo password:"))
    entry = Gtk.Entry()
    entry.set_visibility(False)
    box.add(entry)
    d.show_all()
    resp = d.run()
    pwd = entry.get_text() if resp == Gtk.ResponseType.OK else None
    d.destroy()
    return pwd

class VMSettingsDialog(Gtk.Dialog):
    def __init__(self, parent, config):
        super().__init__(title="Edit VM Settings", transient_for=parent)
        self.set_default_size(500,400)
        self.config = config.copy()
        box = self.get_content_area()
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_margin_top(10); grid.set_margin_bottom(10)
        grid.set_margin_start(10); grid.set_margin_end(10)
        grid.attach(Gtk.Label(label="ISO Path:"), 0,0,1,1)
        self.entry_iso = Gtk.Entry(text=self.config.get("iso", ""))
        btn = Gtk.Button(label="Browse")
        btn.connect("clicked", self.on_iso_browse)
        grid.attach(self.entry_iso, 1,0,1,1)
        grid.attach(btn, 2,0,1,1)
        grid.attach(Gtk.Label(label="CPU Cores:"), 0,1,1,1)
        self.spin_cpu = Gtk.SpinButton.new_with_range(1,32,1)
        self.spin_cpu.set_value(self.config.get("cpu",2))
        grid.attach(self.spin_cpu, 1,1,2,1)
        grid.attach(Gtk.Label(label="RAM (MiB):"), 0,2,1,1)
        self.spin_ram = Gtk.SpinButton.new_with_range(256,131072,256)
        self.spin_ram.set_value(self.config.get("ram",4096))
        grid.attach(self.spin_ram, 1,2,2,1)
        grid.attach(Gtk.Label(label="Firmware:"), 0,3,1,1)
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
        grid.attach(fw_box, 1,3,2,1)
        grid.attach(Gtk.Label(label="Display:"), 0,4,1,1)
        self.combo_disp = Gtk.ComboBoxText()
        for opt in ["gtk (default)", "qxl", "spice"]:
            self.combo_disp.append_text(opt)
        self.combo_disp.set_active(0)
        grid.attach(self.combo_disp, 1,4,2,1)
        grid.attach(Gtk.Label(label="3D Acceleration:"), 0,5,1,1)
        self.check_3d = Gtk.CheckButton()
        self.check_3d.set_active(self.config.get("3d_acceleration", False))
        grid.attach(self.check_3d, 1,5,2,1)
        box.add(grid)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Apply", Gtk.ResponseType.OK)
        self.show_all()
    def on_iso_browse(self, w):
        d = Gtk.FileChooserDialog(title="Select ISO File", parent=self,
                                  action=Gtk.FileChooserAction.OPEN)
        d.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        f = Gtk.FileFilter(); f.set_name("ISO files"); f.add_pattern("*.iso"); d.add_filter(f)
        if d.run() == Gtk.ResponseType.OK:
            self.entry_iso.set_text(d.get_filename())
        d.destroy()
    def get_updated_config(self):
        firmware = "BIOS"
        if self.radio_uefi.get_active():
            firmware = "UEFI"
        elif self.radio_secure.get_active():
            firmware = "UEFI+Secure Boot"
        self.config["iso"] = urllib.parse.unquote(self.entry_iso.get_text())
        self.config["cpu"] = self.spin_cpu.get_value_as_int()
        self.config["ram"] = self.spin_ram.get_value_as_int()
        self.config["firmware"] = firmware
        self.config["display"] = self.combo_disp.get_active_text()
        self.config["3d_acceleration"] = self.check_3d.get_active()
        if self.config["firmware"] in ["UEFI", "UEFI+Secure Boot"]:
            copy_uefi_files(self.config)
        self.config["launch_cmd"] = build_launch_command(self.config)
        return self.config

class VMCloneDialog(Gtk.Dialog):
    def __init__(self, parent, vm_config):
        super().__init__(title="Clone VM", transient_for=parent)
        self.set_default_size(400,200)
        self.original_vm = vm_config
        box = self.get_content_area()
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_margin_top(10); grid.set_margin_bottom(10)
        grid.set_margin_start(10); grid.set_margin_end(10)
        grid.attach(Gtk.Label(label="New VM Name:"), 0,0,1,1)
        self.entry_new_name = Gtk.Entry(text=self.original_vm["name"] + "_clone")
        grid.attach(self.entry_new_name, 1,0,2,1)
        grid.attach(Gtk.Label(label="New Directory:"), 0,1,1,1)
        self.entry_new_path = Gtk.Entry()
        btn = Gtk.Button(label="Browse")
        btn.connect("clicked", self.on_browse)
        grid.attach(self.entry_new_path, 1,1,1,1)
        grid.attach(btn, 2,1,1,1)
        box.add(grid)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Clone", Gtk.ResponseType.OK)
        self.show_all()
    def on_browse(self, w):
        d = Gtk.FileChooserDialog(title="Select Destination Folder", parent=self,
                                  action=Gtk.FileChooserAction.SELECT_FOLDER)
        d.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Select", Gtk.ResponseType.OK)
        if d.run() == Gtk.ResponseType.OK:
            self.entry_new_path.set_text(d.get_filename())
        d.destroy()
    def get_clone_info(self):
        return {"new_name": self.entry_new_name.get_text(), "new_path": self.entry_new_path.get_text()}

class QEMUManagerMain(Gtk.Window):
    def __init__(self):
        super().__init__(title="QEMU VM Manager")
        self.set_default_size(600,400)
        self.vm_configs = load_all_vm_configs()
        self.build_ui()
        self.apply_css()
    def build_ui(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(10); vbox.set_margin_bottom(10)
        vbox.set_margin_start(10); vbox.set_margin_end(10)
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
        css = b"""
        window { background-color: rgba(255,255,255,0.15); }
        .vm-item { background-color: rgba(50,50,50,0.8); border: 2px solid #555; border-radius: 4px; padding: 5px; margin: 5px; }
        .vm-item label { color: #fff; font-weight: bold; }
        .round-button { border-radius: 16px; padding: 0; background-color: transparent; }
        """
        sp = Gtk.CssProvider()
        sp.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), sp, Gtk.STYLE_PROVIDER_PRIORITY_USER)
    def on_add_vm(self, w):
        d = ISOSelectDialog(self)
        d.show_all()
    def add_vm(self, config):
        save_vm_config(config)
        idx = load_vm_index()
        if config["path"] not in idx:
            idx.append(config["path"])
            save_vm_index(idx)
        self.vm_configs = load_all_vm_configs()
        self.refresh_vm_list()
    def refresh_vm_list(self):
        for row in self.listbox.get_children():
            self.listbox.remove(row)
        for vm in self.vm_configs:
            row = self.create_vm_row(vm)
            self.listbox.add(row)
        self.listbox.show_all()
    def create_vm_row(self, vm):
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
        if event.button == 3:
            menu = self.create_context_menu(vm)
            menu.popup_at_pointer(event)
    def create_context_menu(self, vm):
        menu = Gtk.Menu()
        for text, action in [("Start", self.start_vm), ("Force Shutdown", self.force_shutdown),
                             ("Settings", self.edit_vm), ("Delete", self.delete_vm),
                             ("Clone", self.clone_vm)]:
            item = Gtk.MenuItem(label=text)
            item.connect("activate", lambda b, a=action, vm=vm: a(vm))
            menu.append(item)
        menu.show_all()
        return menu
    def start_vm(self, vm):
        launch_cmd = build_launch_command(vm)
        if not launch_cmd:
            show_error_dialog("QEMU binary not found!")
            return
        disk = vm["disk_image"]
        if not os.path.exists(disk):
            img = shutil.which("qemu-img")
            if img:
                try:
                    subprocess.check_call([img, "create", "-f", vm["disk_type"], disk, f"{vm['disk']}G"])
                except Exception:
                    show_error_dialog("Failed to create disk image!")
                    return
            else:
                show_error_dialog("qemu-img not found! Cannot create disk image.")
                return
        try:
            subprocess.Popen(launch_cmd)
        except Exception:
            show_error_dialog("Failed to execute QEMU command.")
    def force_shutdown(self, vm):
        show_error_dialog("Force shutdown is not implemented yet.")
    def edit_vm(self, vm):
        d = VMSettingsDialog(self, vm)
        if d.run() == Gtk.ResponseType.OK:
            updated = d.get_updated_config()
            save_vm_config(updated)
            idx = load_vm_index()
            if vm["path"] in idx:
                idx[idx.index(vm["path"])] = updated["path"]
            save_vm_index(idx)
            self.vm_configs = load_all_vm_configs()
            self.refresh_vm_list()
        d.destroy()
    def delete_vm(self, vm):
        d = Gtk.MessageDialog(transient_for=self, message_type=Gtk.MessageType.WARNING,
                              buttons=Gtk.ButtonsType.OK_CANCEL,
                              text=f"Delete VM '{vm['name']}' and all its files?")
        if d.run() == Gtk.ResponseType.OK:
            idx = load_vm_index()
            if vm["path"] in idx:
                idx.remove(vm["path"])
                save_vm_index(idx)
            try:
                shutil.rmtree(vm["path"])
            except Exception:
                show_error_dialog("Failed to delete VM directory!")
            self.vm_configs = [c for c in self.vm_configs if c["path"] != vm["path"]]
            self.refresh_vm_list()
        d.destroy()
    def clone_vm(self, vm):
        d = VMCloneDialog(self, vm)
        if d.run() == Gtk.ResponseType.OK:
            info = d.get_clone_info()
            new_vm = vm.copy()
            new_vm["name"] = info["new_name"]
            new_vm["path"] = info["new_path"]
            new_vm["disk_image"] = os.path.join(new_vm["path"], new_vm["name"] + ".img")
            self.add_vm(new_vm)
        d.destroy()

def main():
    win = QEMUManagerMain()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
