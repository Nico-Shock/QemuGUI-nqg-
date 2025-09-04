#!/usr/bin/env python3
import os
import json
import subprocess
import shutil
import threading
import urllib.parse
import logging
import re
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib
import webbrowser
import psutil

def find_ovmf_source_dir():
    candidates = [
        "/usr/share/edk2-ovmf/x64",
        "/usr/share/edk2-ovmf",
        "/usr/share/edk2/ovmf",
        "/usr/share/OVMF",
        "/usr/share/ovmf",
        "/usr/share/qemu",
        "/usr/share/edk2"
    ]
    for d in candidates:
        if os.path.isdir(d):
            files = os.listdir(d)
            if any(f.startswith("OVMF_CODE") for f in files) or any(f.endswith(".secboot.fd") for f in files):
                return d
    return None

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".nqg")
if not os.path.exists(CONFIG_DIR):
    os.makedirs(CONFIG_DIR)
CONFIG_FILE = os.path.join(CONFIG_DIR, "vms_index.json")
LOG_FILE = os.path.join(CONFIG_DIR, "nqg.log")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_host_os():
    if os.path.exists("/etc/arch-release"):
        return "arch"
    elif os.path.exists("/etc/debian_version"):
        return "debian"
    elif os.path.exists("/etc/fedora-release"):
        return "fedora"
    elif os.path.exists("/etc/serpentos-release"):
        return "serpentos"
    else:
        return "other"

def copy_uefi_files(config, parent_window=None):
    host_os = get_host_os()
    ovmf_dir = os.path.join(config["path"], "ovmf")
    os.makedirs(ovmf_dir, exist_ok=True)
    src_dir = find_ovmf_source_dir()
    if not src_dir:
        GLib.idle_add(show_detailed_error_dialog, "OVMF folder not found.", "No valid OVMF source directory detected. Please install 'edk2-ovmf'.", parent_window)
        return False

    firmware = config.get("firmware", "")
    files_to_copy = {
        "UEFI": {"OVMF_CODE.fd": "OVMF_CODE.fd"},
        "UEFI+Secure Boot": {"OVMF_CODE.secboot.fd": "OVMF_CODE.fd", "OVMF_VARS.fd": "OVMF_VARS.fd"}
    }

    selected_files = files_to_copy.get(firmware, {})

    for src_name, dst_name in selected_files.items():
        src = os.path.join(src_dir, src_name)
        dst = os.path.join(ovmf_dir, dst_name)
        if os.path.exists(src):
            try:
                shutil.copy(src, dst)
                logging.info(f"Copied {src} to {dst}")
            except Exception as e:
                logging.error(f"Copy failed {src} to {dst}: {e}")
                GLib.idle_add(show_detailed_error_dialog, f"Failed to copy UEFI file: {src_name}", str(e), parent_window)
                return False
        else:
            logging.warning(f"Source file {src} does not exist.")
            GLib.idle_add(show_detailed_error_dialog, "UEFI source file not found.", f"File not found: {src}", parent_window)
            return False

    if firmware == "UEFI":
        config["ovmf_code"] = os.path.join(ovmf_dir, "OVMF_CODE.fd")
        config.pop("ovmf_code_secure", None)
        config.pop("ovmf_vars_secure", None)
    elif firmware == "UEFI+Secure Boot":
        config["ovmf_code_secure"] = os.path.join(ovmf_dir, "OVMF_CODE.fd")
        config["ovmf_vars_secure"] = os.path.join(ovmf_dir, "OVMF_VARS.fd")
        config.pop("ovmf_code", None)

    return True

def delete_ovmf_dir(config):
    d = os.path.join(config["path"], "ovmf")
    if os.path.exists(d):
        try:
            shutil.rmtree(d)
            logging.info(f"Deleted {d}")
            return True
        except OSError as e:
            show_detailed_error_dialog("Error deleting OVMF folder.", str(e), None)
            return False
    return True

def validate_vm_config(vm):
    if not os.path.exists(vm["disk_image"]):
        show_detailed_error_dialog("Disk image missing.", vm["disk_image"], None)
        return False
    if vm["firmware"] == "UEFI" and not os.path.exists(vm.get("ovmf_code", "")):
        show_detailed_error_dialog("UEFI file missing.", vm.get("ovmf_code", ""), None)
        return False
    if vm["firmware"] == "UEFI+Secure Boot":
        if not os.path.exists(vm.get("ovmf_code_secure", "")) or not os.path.exists(vm.get("ovmf_vars_secure", "")):
            show_detailed_error_dialog("Secure Boot files missing.", f"Code: {vm.get('ovmf_code_secure', '')}\nVars: {vm.get('ovmf_vars_secure', '')}", None)
            return False
    if vm.get("iso_enabled") and vm.get("iso") and not os.path.exists(vm["iso"]):
        show_detailed_error_dialog("ISO file missing.", vm["iso"], None)
        return False
    if vm.get("tpm_enabled"):
        if not shutil.which("swtpm"):
            show_detailed_error_dialog("TPM emulator 'swtpm' not found.", "Please install swtpm package.", None)
            return False
    return True

def build_launch_command(config):
    arch = "x86_64"
    qemu = shutil.which(f"qemu-system-{arch}")
    if not qemu:
        show_detailed_error_dialog("QEMU not found!", f"qemu-system-{arch} is not in your PATH.", None)
        return None
    cmd = [qemu, "-enable-kvm", "-cpu", "host", "-smp", str(config["cpu"]), "-m", str(config["ram"]), "-drive", f"file={config['disk_image']},format={config['disk_type']},if=virtio", "-boot", "order=dc,menu=off", "-usb", "-device", "usb-tablet", "-netdev", "user,id=net0,hostfwd=tcp::5555-:22", "-device", "virtio-net-pci,netdev=net0"]
    if config.get("3d_acceleration"):
        cmd += ["-device", "virtio-vga-gl", "-display", "egl-headless,gl=on"]
    else:
        cmd += ["-device", "virtio-vga"]
    disp = config.get("display", "").lower()
    if disp == "gtk (default)":
        cmd += ["-display", "gtk,gl=on" if config.get("3d_acceleration") else "gtk"]
    elif disp == "sdl":
        cmd += ["-display", "sdl,gl=on" if config.get("3d_acceleration") else "sdl"]
    elif disp == "spice (virtio)":
        cmd += ["-spice", "port=5930,disable-ticketing=on", "-device", "virtio-serial", "-chardev", "spicevmc,id=spicechannel0,name=vdagent", "-device", "virtserialport,chardev=spicechannel0,name=com.redhat.spice.0"]
        cmd += ["-display", "spice-app,gl=on" if config.get("3d_acceleration") else "spice-app"]
    elif disp == "virtio":
        cmd += ["-display", "egl-headless,gl=on"]
    elif disp == "qemu":
        cmd += ["-display", "none"]
    if config.get("iso_enabled") and config.get("iso"):
        cmd += ["-cdrom", config["iso"]]
    if config["firmware"] == "UEFI" and config.get("ovmf_code"):
        cmd += ["-drive", f"if=pflash,format=raw,readonly=on,file={config['ovmf_code']}"]
    if config["firmware"] == "UEFI+Secure Boot" and config.get("ovmf_code_secure") and config.get("ovmf_vars_secure"):
        cmd += ["-drive", f"if=pflash,format=raw,readonly=on,file={config.get('ovmf_code_secure','')}", "-drive", f"if=pflash,format=raw,file={config.get('ovmf_vars_secure','')}"]
    if config.get("tpm_enabled"):
        tpm_dir = os.path.join(config["path"], "tpm")
        os.makedirs(tpm_dir, exist_ok=True)
        sock = os.path.join(tpm_dir, "swtpm-sock")
        try:
            subprocess.Popen(["swtpm", "socket", "--tpm2", "--tpmstate", f"dir={tpm_dir}", "--ctrl", f"type=unixio,path={sock}", "--log", "level=0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            cmd += ["-chardev", f"socket,id=chrtpm,path={sock}", "-tpmdev", "emulator,id=tpm0,chardev=chrtpm", "-device", "tpm-tis,tpmdev=tpm0"]
        except FileNotFoundError:
             show_detailed_error_dialog("swtpm not found.", "TPM cannot be enabled.", None)
             config["tpm_enabled"] = False
    logging.info("Built launch command: " + " ".join(cmd))
    return cmd

def list_snapshots(vm):
    qi = shutil.which("qemu-img")
    if not qi or not os.path.exists(vm["disk_image"]):
        return []
    try:
        out = subprocess.check_output([qi, "snapshot", "-l", vm["disk_image"]], universal_newlines=True, stderr=subprocess.PIPE)
        lines = out.splitlines()
        if len(lines) < 2:
            return []
        snaps = [line.split()[1] for line in lines[2:] if line and line.strip() and line.split()[0].isdigit()]
        return snaps
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to list snapshots for {vm['name']}: {e.stderr}")
        return []

def create_snapshot_cmd(vm, snap_name):
    qi = shutil.which("qemu-img")
    if not qi or not snap_name or re.search(r'[<>:"/\\|?*]', snap_name):
        return False, "Invalid snapshot name or qemu-img not found."
    try:
        subprocess.run([qi, "snapshot", "-c", snap_name, vm["disk_image"]], check=True, capture_output=True, text=True)
        return True, "Snapshot created successfully."
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to create snapshot '{snap_name}': {e.stderr}")
        return False, e.stderr

def restore_snapshot_cmd(vm, snap_name):
    qi = shutil.which("qemu-img")
    if not qi:
        return False, "qemu-img not found."
    try:
        subprocess.run([qi, "snapshot", "-a", snap_name, vm["disk_image"]], check=True, capture_output=True, text=True)
        return True, f"Snapshot '{snap_name}' restored."
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to restore snapshot '{snap_name}': {e.stderr}")
        return False, e.stderr

def delete_snapshot_cmd(vm, snap_name):
    qi = shutil.which("qemu-img")
    if not qi:
        return False, "qemu-img not found."
    try:
        subprocess.run([qi, "snapshot", "-d", snap_name, vm["disk_image"]], check=True, capture_output=True, text=True)
        return True, f"Snapshot '{snap_name}' deleted."
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to delete snapshot '{snap_name}': {e.stderr}")
        return False, e.stderr

def load_vm_index():
    if os.path.exists(CONFIG_FILE) and os.path.getsize(CONFIG_FILE) > 0:
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

def save_vm_index(index):
    with open(CONFIG_FILE, "w") as f:
        json.dump(index, f, indent=4)

def load_all_vm_configs():
    configs = []
    index = load_vm_index()
    valid_paths = []
    for p in index:
        if not os.path.isdir(p):
            continue
        config_found = False
        for fn in os.listdir(p):
            if fn.endswith(".json"):
                try:
                    with open(os.path.join(p, fn)) as f:
                        configs.append(json.load(f))
                    config_found = True
                    break
                except (json.JSONDecodeError, KeyError):
                    logging.warning(f"Could not load or parse config in {p}")
        if config_found:
            valid_paths.append(p)
    if len(valid_paths) != len(index):
        save_vm_index(valid_paths)
    return configs

def save_vm_config(config):
    fn = os.path.join(config["path"], config["name"] + ".json")
    with open(fn, "w") as f:
        json.dump(config, f, indent=4)

def show_info_dialog(message, details, parent):
    dlg = Gtk.MessageDialog(transient_for=parent, flags=0, message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK, text=message)
    dlg.set_secondary_text(details)
    dlg.run()
    dlg.destroy()

def show_detailed_error_dialog(message, details, parent):
    dlg = Gtk.Dialog(title="Error", transient_for=parent, flags=0)
    dlg.add_button("OK", Gtk.ResponseType.OK)
    box = dlg.get_content_area()
    box.set_spacing(10)
    box.set_margin_top(10)
    box.set_margin_bottom(10)
    box.set_margin_start(10)
    box.set_margin_end(10)
    box.add(Gtk.Label(label=message))
    if details:
        exp = Gtk.Expander(label="Details")
        exp.set_expanded(False)
        exp_content = Gtk.Label(label=details)
        exp_content.set_selectable(True)
        exp_content.set_line_wrap(True)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.add(exp_content)
        scrolled.set_min_content_height(100)
        exp.add(scrolled)
        box.add(exp)
    dlg.show_all()
    dlg.run()
    dlg.destroy()

class ProgressDialog(Gtk.Dialog):
    def __init__(self, parent, title="Processing..."):
        super().__init__(title=title, transient_for=parent)
        self.set_modal(True)
        self.set_default_size(350, 120)
        self.set_resizable(False)
        box = self.get_content_area()
        box.set_spacing(10)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_margin_start(20)
        box.set_margin_end(20)
        self.label = Gtk.Label(label=title)
        box.add(self.label)
        self.progress = Gtk.ProgressBar()
        self.progress.set_text("0%")
        self.progress.set_show_text(True)
        box.add(self.progress)
        self.show_all()

    def update(self, fraction, text):
        self.progress.set_fraction(fraction)
        if text:
            self.progress.set_text(text)
        return True

    def pulse(self, text):
        self.progress.pulse()
        if text:
             self.progress.set_text(text)
        return True

    def set_text(self, text):
        self.label.set_text(text)

class ISOSelectDialog(Gtk.Window):
    def __init__(self, parent):
        super().__init__(title="Select ISO for Virtual Machine", transient_for=parent)
        self.parent = parent
        self.set_default_size(400,300)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_resizable(True)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(20)
        vbox.set_margin_bottom(20)
        vbox.set_margin_start(20)
        vbox.set_margin_end(20)
        btn = Gtk.Button(label="+")
        btn.set_size_request(150,150)
        btn.set_tooltip_text("Select an ISO file")
        btn.connect("clicked", self.on_plus_clicked)
        vbox.pack_start(btn, False, False, 0)
        drop = Gtk.EventBox()
        drop.set_size_request(300,150)
        drop.get_style_context().add_class("iso-drop-area")
        drop.connect("drag-data-received", self.on_drag_received)
        drop.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        target = Gtk.TargetEntry.new("text/uri-list", 0, 0)
        drop.drag_dest_set_target_list(Gtk.TargetList.new([target]))
        vbox.pack_start(drop, True, True, 0)
        vbox.pack_start(Gtk.Label(label="Drag ISO here or click '+'"), False, False, 0)
        skip_btn = Gtk.Button(label="Skip")
        skip_btn.set_tooltip_text("Continue without selecting an ISO")
        skip_btn.connect("clicked", self.on_skip_clicked)
        vbox.pack_start(skip_btn, False, False, 0)
        self.add(vbox)
    def on_plus_clicked(self, w):
        d = Gtk.FileChooserDialog(title="Select ISO File", parent=self,
                                  action=Gtk.FileChooserAction.OPEN)
        d.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        f = Gtk.FileFilter()
        f.set_name("ISO Files")
        f.add_pattern("*.iso")
        d.add_filter(f)
        if d.run() == Gtk.ResponseType.OK:
            self.iso_chosen(d.get_filename())
        d.destroy()
    def on_drag_received(self, w, dc, x, y, data, info, time):
        uris = data.get_uris()
        if uris:
            self.iso_chosen(urllib.parse.unquote(uris[0].replace("file://", "").strip()))
    def on_skip_clicked(self, w):
        self.destroy()
        d = VMCreateDialog(self.parent)
        if d.run() == Gtk.ResponseType.OK:
            config = d.get_vm_config()
            if config:
                self.parent.add_vm(config)
        d.destroy()
    def iso_chosen(self, iso_path):
        self.destroy()
        d = VMCreateDialog(self.parent, iso_path)
        if d.run() == Gtk.ResponseType.OK:
            config = d.get_vm_config()
            if config:
                self.parent.add_vm(config)
        d.destroy()

class VMCreateDialog(Gtk.Dialog):
    def __init__(self, parent, iso_path=None):
        super().__init__(title="New Virtual Machine Configuration", transient_for=parent)
        self.set_default_size(500,500)
        self.set_resizable(True)
        self.iso_path = iso_path
        box = self.get_content_area()
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)
        grid.attach(Gtk.Label(label="Virtual Machine Name:"), 0, 0, 1, 1)
        self.entry_name = Gtk.Entry()
        self.entry_name.set_tooltip_text("Enter a unique name for the VM")
        grid.attach(self.entry_name, 1, 0, 2, 1)
        grid.attach(Gtk.Label(label="Virtual Machine Directory:"), 0, 1, 1, 1)
        self.entry_path = Gtk.Entry()
        self.entry_path.set_text(os.path.join(os.path.expanduser("~"), "nqg_vms"))
        self.entry_path.set_tooltip_text("Select a directory to store VM files")
        btn = Gtk.Button(label="Browse")
        btn.set_tooltip_text("Choose a directory")
        btn.connect("clicked", self.on_browse)
        grid.attach(self.entry_path, 1, 1, 1, 1)
        grid.attach(btn, 2, 1, 1, 1)
        grid.attach(Gtk.Label(label="CPU Cores:"), 0, 2, 1, 1)
        self.spin_cpu = Gtk.SpinButton.new_with_range(1, os.cpu_count(), 1)
        self.spin_cpu.set_value(2)
        self.spin_cpu.set_tooltip_text("Number of CPU cores for the VM")
        grid.attach(self.spin_cpu, 1, 2, 2, 1)
        grid.attach(Gtk.Label(label=f"Max: {os.cpu_count()}"), 3, 2, 1, 1)
        grid.attach(Gtk.Label(label="RAM (MiB):"), 0, 3, 1, 1)
        self.spin_ram = Gtk.SpinButton.new_with_range(256, 131072, 256)
        self.spin_ram.set_value(4096)
        self.spin_ram.set_tooltip_text("Memory allocation in MiB")
        grid.attach(self.spin_ram, 1, 3, 2, 1)
        grid.attach(Gtk.Label(label="Max: 131072 MiB"), 3, 3, 1, 1)
        grid.attach(Gtk.Label(label="Disk Size (GB):"), 0, 4, 1, 1)
        self.spin_disk = Gtk.SpinButton.new_with_range(1, 128, 1)
        self.spin_disk.set_value(40)
        self.spin_disk.set_tooltip_text("Disk size in GB")
        grid.attach(self.spin_disk, 1, 4, 2, 1)
        grid.attach(Gtk.Label(label="Disk Type:"), 0, 5, 1, 1)
        self.radio_qcow2 = Gtk.RadioButton.new_with_label_from_widget(None, "qcow2 (Recommended)")
        self.radio_qcow2.set_tooltip_text("Efficient disk format with snapshot support")
        self.radio_raw = Gtk.RadioButton.new_with_label_from_widget(self.radio_qcow2, "raw (Full)")
        self.radio_raw.set_tooltip_text("Full disk allocation, higher performance")
        grid.attach(self.radio_qcow2, 1, 5, 1, 1)
        grid.attach(self.radio_raw, 2, 5, 1, 1)
        grid.attach(Gtk.Label(label="Firmware:"), 0, 6, 1, 1)
        fw_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.radio_bios = Gtk.RadioButton.new_with_label_from_widget(None, "BIOS")
        self.radio_bios.set_tooltip_text("Traditional BIOS boot")
        self.radio_uefi = Gtk.RadioButton.new_with_label_from_widget(self.radio_bios, "UEFI")
        self.radio_uefi.set_tooltip_text("Modern UEFI boot")
        self.radio_secure = Gtk.RadioButton.new_with_label_from_widget(self.radio_bios, "UEFI+Secure Boot")
        self.radio_secure.set_tooltip_text("UEFI with Secure Boot enabled")
        fw_box.pack_start(self.radio_bios, False, False, 0)
        fw_box.pack_start(self.radio_uefi, False, False, 0)
        fw_box.pack_start(self.radio_secure, False, False, 0)
        grid.attach(fw_box, 1, 6, 2, 1)
        grid.attach(Gtk.Label(label="Enable TPM:"), 0, 7, 1, 1)
        self.check_tpm = Gtk.CheckButton()
        self.check_tpm.set_tooltip_text("Enable Trusted Platform Module")
        grid.attach(self.check_tpm, 1, 7, 2, 1)
        grid.attach(Gtk.Label(label="Display:"), 0, 8, 1, 1)
        self.combo_disp = Gtk.ComboBoxText()
        for opt in ["gtk (default)", "sdl", "spice (virtio)", "virtio", "qemu"]:
            self.combo_disp.append_text(opt)
        self.combo_disp.set_active(0)
        self.combo_disp.set_tooltip_text("Select display backend")
        grid.attach(self.combo_disp, 1, 8, 2, 1)
        self.recommend_label = Gtk.Label()
        grid.attach(self.recommend_label, 3, 8, 1, 1)
        self.combo_disp.connect("changed", self.on_display_changed)
        grid.attach(Gtk.Label(label="3D Acceleration:"), 0, 9, 1, 1)
        self.check_3d = Gtk.CheckButton()
        self.check_3d.set_tooltip_text("Enable 3D graphics acceleration")
        grid.attach(self.check_3d, 1, 9, 2, 1)
        box.add(grid)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Create", Gtk.ResponseType.OK)
        self.show_all()
        self.on_display_changed(self.combo_disp)
    def on_display_changed(self, combo):
        selected = combo.get_active_text().lower()
        if "gtk" in selected or "sdl" in selected:
            self.recommend_label.set_text("Recommended for Linux")
            self.check_3d.set_sensitive(True)
        elif "spice" in selected:
            self.recommend_label.set_text("Recommended for Windows")
            self.check_3d.set_sensitive(True)
        elif "virtio" in selected:
            self.recommend_label.set_text("Optimized for Windows with 3D")
            self.check_3d.set_sensitive(True)
        elif "qemu" in selected:
            self.recommend_label.set_text("Headless mode")
            self.check_3d.set_sensitive(False)
            self.check_3d.set_active(False)
    def on_browse(self, w):
        d = Gtk.FileChooserDialog(title="Select Folder", parent=self,
                                  action=Gtk.FileChooserAction.SELECT_FOLDER)
        d.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Select", Gtk.ResponseType.OK)
        if d.run() == Gtk.ResponseType.OK:
            self.entry_path.set_text(d.get_filename())
        d.destroy()
    def get_vm_config(self):
        name = self.entry_name.get_text()
        if not name or re.search(r'[<>:"/\\|?*]', name):
            show_detailed_error_dialog("Invalid VM name.", "Name cannot be empty or contain special characters.", self)
            logging.error(f"Invalid VM name: {name}")
            return None
        path = self.entry_path.get_text()
        if not path:
            show_detailed_error_dialog("Invalid directory.", "Directory path cannot be empty.", self)
            return None
        os.makedirs(path, exist_ok=True)
        if not os.access(path, os.W_OK):
            show_detailed_error_dialog("Directory not writable.", f"Cannot write to the directory: {path}", self)
            logging.error(f"Invalid directory: {path}")
            return None
        total_mem = psutil.virtual_memory().total // (1024 * 1024)
        ram = self.spin_ram.get_value_as_int()
        if ram >= total_mem:
            show_detailed_error_dialog("Invalid RAM.", f"RAM ({ram} MiB) is too close to or exceeds available host memory ({total_mem} MiB).", self)
            logging.error(f"RAM {ram} MiB exceeds available {total_mem} MiB")
            return None
        firmware = "BIOS"
        if self.radio_uefi.get_active(): firmware = "UEFI"
        elif self.radio_secure.get_active(): firmware = "UEFI+Secure Boot"
        config = {
            "name": name, "path": path, "cpu": self.spin_cpu.get_value_as_int(),
            "ram": ram, "disk": self.spin_disk.get_value_as_int(),
            "disk_type": "qcow2" if self.radio_qcow2.get_active() else "raw",
            "firmware": firmware, "display": self.combo_disp.get_active_text(),
            "iso": self.iso_path or "", "iso_enabled": bool(self.iso_path),
            "3d_acceleration": self.check_3d.get_active(),
            "disk_image": os.path.join(path, name + ".img"),
            "tpm_enabled": self.check_tpm.get_active(),
        }
        if not os.path.exists(config["disk_image"]):
            qemu_img = shutil.which("qemu-img")
            if qemu_img:
                try:
                    subprocess.run([qemu_img, "create", "-f", config["disk_type"],
                                   config["disk_image"], f"{config['disk']}G"], check=True, capture_output=True, text=True)
                    logging.info(f"Created disk image {config['disk_image']}")
                except subprocess.CalledProcessError as e:
                    show_detailed_error_dialog(f"Error creating disk: {e.stderr}", str(e), self)
                    logging.error(f"Error creating disk {config['disk_image']}: {e.stderr}")
                    return None
            else:
                show_detailed_error_dialog("qemu-img not found.", "Please install QEMU.", self)
                logging.error("qemu-img not found for disk creation")
                return None
        if config["firmware"] in ["UEFI", "UEFI+Secure Boot"]:
            if not copy_uefi_files(config, self):
                show_detailed_error_dialog("Failed to copy UEFI files. Using BIOS firmware instead.", "Check OVMF installation and permissions.", self)
                logging.warning("Failed to copy UEFI files, falling back to BIOS")
                config["firmware"] = "BIOS"
        config["launch_cmd"] = build_launch_command(config)
        return config

class VMSettingsDialog(Gtk.Dialog):
    def __init__(self, parent, config):
        super().__init__(title="Edit Virtual Machine Settings", transient_for=parent)
        self.set_default_size(500,450)
        self.set_resizable(True)
        self.config = config.copy()
        self.original_name = config["name"]
        self.original_path = config["path"]
        box = self.get_content_area()
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)
        grid.attach(Gtk.Label(label="Virtual Machine Name:"), 0, 0, 1, 1)
        self.entry_name = Gtk.Entry()
        self.entry_name.set_text(self.config.get("name", ""))
        self.entry_name.set_tooltip_text("Edit the VM name")
        grid.attach(self.entry_name, 1, 0, 3, 1)
        grid.attach(Gtk.Label(label="ISO Path:"), 0, 1, 1, 1)
        self.entry_iso = Gtk.Entry()
        self.entry_iso.set_text(self.config.get("iso", ""))
        self.entry_iso.set_tooltip_text("Path to the ISO file")
        grid.attach(self.entry_iso, 1, 1, 2, 1)
        self.btn_iso_browse = Gtk.Button(label="Browse")
        self.btn_iso_browse.set_tooltip_text("Select a new ISO file")
        self.btn_iso_browse.connect("clicked", self.on_iso_browse)
        grid.attach(self.btn_iso_browse, 3, 1, 1, 1)
        self.check_iso_enable = Gtk.CheckButton()
        self.check_iso_enable.set_active(self.config.get("iso_enabled", False))
        self.check_iso_enable.set_tooltip_text("Enable or disable ISO usage")
        self.check_iso_enable.connect("toggled", self.on_iso_enabled_toggled_settings)
        grid.attach(self.check_iso_enable, 4, 1, 1, 1)
        grid.attach(Gtk.Label(label="CPU Cores:"), 0, 2, 1, 1)
        self.spin_cpu = Gtk.SpinButton.new_with_range(1, os.cpu_count(), 1)
        self.spin_cpu.set_value(self.config.get("cpu", 2))
        self.spin_cpu.set_tooltip_text("Number of CPU cores for the VM")
        grid.attach(self.spin_cpu, 1, 2, 3, 1)
        grid.attach(Gtk.Label(label=f"Max: {os.cpu_count()}"), 4, 2, 1, 1)
        grid.attach(Gtk.Label(label="RAM (MiB):"), 0, 3, 1, 1)
        self.spin_ram = Gtk.SpinButton.new_with_range(256, 131072, 256)
        self.spin_ram.set_value(self.config.get("ram", 4096))
        self.spin_ram.set_tooltip_text("Memory allocation in MiB")
        grid.attach(self.spin_ram, 1, 3, 3, 1)
        grid.attach(Gtk.Label(label="Max: 131072 MiB"), 4, 3, 1, 1)
        grid.attach(Gtk.Label(label="Firmware:"), 0, 4, 1, 1)
        fw_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.radio_bios = Gtk.RadioButton.new_with_label_from_widget(None, "BIOS")
        self.radio_bios.set_tooltip_text("Traditional BIOS boot")
        self.radio_uefi = Gtk.RadioButton.new_with_label_from_widget(self.radio_bios, "UEFI")
        self.radio_uefi.set_tooltip_text("Modern UEFI boot")
        self.radio_secure = Gtk.RadioButton.new_with_label_from_widget(self.radio_bios, "UEFI+Secure Boot")
        self.radio_secure.set_tooltip_text("UEFI with Secure Boot enabled")
        fw_box.pack_start(self.radio_bios, False, False, 0)
        fw_box.pack_start(self.radio_uefi, False, False, 0)
        fw_box.pack_start(self.radio_secure, False, False, 0)
        if self.config.get("firmware", "BIOS") == "UEFI": self.radio_uefi.set_active(True)
        elif self.config.get("firmware") == "UEFI+Secure Boot": self.radio_secure.set_active(True)
        else: self.radio_bios.set_active(True)
        grid.attach(fw_box, 1, 4, 3, 1)
        grid.attach(Gtk.Label(label="Enable TPM:"), 0, 5, 1, 1)
        self.check_tpm = Gtk.CheckButton()
        self.check_tpm.set_active(self.config.get("tpm_enabled", False))
        self.check_tpm.set_tooltip_text("Enable Trusted Platform Module")
        grid.attach(self.check_tpm, 1, 5, 3, 1)
        grid.attach(Gtk.Label(label="Display:"), 0, 6, 1, 1)
        self.combo_disp = Gtk.ComboBoxText()
        disp_opts = ["gtk (default)", "sdl", "spice (virtio)", "virtio", "qemu"]
        for opt in disp_opts: self.combo_disp.append_text(opt)
        active_index = disp_opts.index(self.config.get("display", disp_opts[0])) if self.config.get("display") in disp_opts else 0
        self.combo_disp.set_active(active_index)
        self.combo_disp.set_tooltip_text("Select display backend")
        grid.attach(self.combo_disp, 1, 6, 3, 1)
        self.recommend_label = Gtk.Label()
        grid.attach(self.recommend_label, 4, 6, 1, 1)
        self.combo_disp.connect("changed", self.on_display_changed)
        grid.attach(Gtk.Label(label="3D Acceleration:"), 0, 7, 1, 1)
        self.check_3d = Gtk.CheckButton()
        self.check_3d.set_active(self.config.get("3d_acceleration", False))
        self.check_3d.set_tooltip_text("Enable 3D graphics acceleration")
        grid.attach(self.check_3d, 1, 7, 3, 1)
        box.add(grid)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Apply", Gtk.ResponseType.OK)
        self.show_all()
        self.on_display_changed(self.combo_disp)
        self.initial_firmware = self.config.get("firmware", "BIOS")
        self.update_iso_entry_sensitivity_settings()
    def on_display_changed(self, combo):
        selected = combo.get_active_text().lower()
        if "gtk" in selected or "sdl" in selected:
            self.recommend_label.set_text("Recommended for Linux")
            self.check_3d.set_sensitive(True)
        elif "spice" in selected:
            self.recommend_label.set_text("Recommended for Windows")
            self.check_3d.set_sensitive(True)
        elif "virtio" in selected:
            self.recommend_label.set_text("Optimized for Windows with 3D")
            self.check_3d.set_sensitive(True)
        elif "qemu" in selected:
            self.recommend_label.set_text("Headless mode")
            self.check_3d.set_sensitive(False)
            self.check_3d.set_active(False)
    def on_iso_enabled_toggled_settings(self, check):
        self.update_iso_entry_sensitivity_settings()
    def update_iso_entry_sensitivity_settings(self):
        is_enabled = self.check_iso_enable.get_active()
        self.entry_iso.set_sensitive(is_enabled)
        self.btn_iso_browse.set_sensitive(is_enabled)
    def on_iso_browse(self, w):
        d = Gtk.FileChooserDialog(title="Select ISO File", parent=self, action=Gtk.FileChooserAction.OPEN)
        d.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        f = Gtk.FileFilter(); f.set_name("ISO Files"); f.add_pattern("*.iso"); d.add_filter(f)
        if d.run() == Gtk.ResponseType.OK: self.entry_iso.set_text(d.get_filename())
        d.destroy()
    def get_updated_config(self):
        new_config = self.config.copy()
        new_name = self.entry_name.get_text()
        if not new_name or re.search(r'[<>:"/\\|?*]', new_name):
            show_detailed_error_dialog("Invalid VM name.", "Name cannot be empty or contain special characters.", self)
            return None
        total_mem = psutil.virtual_memory().total // (1024 * 1024)
        ram = self.spin_ram.get_value_as_int()
        if ram >= total_mem:
            show_detailed_error_dialog("Invalid RAM.", f"RAM ({ram} MiB) is too close to or exceeds host memory ({total_mem} MiB).", self)
            return None

        if new_name != self.original_name:
            old_conf_file = os.path.join(self.original_path, f"{self.original_name}.json")
            new_conf_file = os.path.join(self.original_path, f"{new_name}.json")
            old_disk_image = new_config["disk_image"]
            new_disk_image = os.path.join(self.original_path, f"{new_name}.img")
            try:
                if os.path.exists(old_conf_file): os.rename(old_conf_file, new_conf_file)
                if os.path.exists(old_disk_image): os.rename(old_disk_image, new_disk_image)
                new_config["disk_image"] = new_disk_image
            except OSError as e:
                show_detailed_error_dialog(f"Error renaming files: {e}", str(e), self)
                return None

        new_config["name"] = new_name
        new_config["iso"] = self.entry_iso.get_text() if self.check_iso_enable.get_active() else ""
        new_config["iso_enabled"] = self.check_iso_enable.get_active()
        new_config["cpu"] = self.spin_cpu.get_value_as_int()
        new_config["ram"] = ram
        new_firmware = "BIOS"
        if self.radio_uefi.get_active(): new_firmware = "UEFI"
        elif self.radio_secure.get_active(): new_firmware = "UEFI+Secure Boot"
        new_config["firmware"] = new_firmware
        new_config["display"] = self.combo_disp.get_active_text()
        new_config["3d_acceleration"] = self.check_3d.get_active()
        new_config["tpm_enabled"] = self.check_tpm.get_active()
        if "arch" in new_config:
            del new_config["arch"]

        if new_config["firmware"] != self.initial_firmware:
            if new_config["firmware"] in ["UEFI", "UEFI+Secure Boot"]:
                if not copy_uefi_files(new_config, self):
                    show_detailed_error_dialog("Error copying UEFI files.", "Reverting firmware change.", self)
                    new_config["firmware"] = self.initial_firmware
            else:
                delete_ovmf_dir(new_config)
                new_config.pop("ovmf_code", None)
                new_config.pop("ovmf_code_secure", None)
                new_config.pop("ovmf_vars_secure", None)

        new_config["launch_cmd"] = build_launch_command(new_config)
        return new_config

class VMCloneDialog(Gtk.Dialog):
    def __init__(self, parent, vm_config):
        super().__init__(title="Clone Virtual Machine", transient_for=parent)
        self.set_default_size(400,200)
        self.set_resizable(True)
        self.original_vm = vm_config
        box = self.get_content_area()
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)
        grid.attach(Gtk.Label(label="New Virtual Machine Name:"), 0, 0, 1, 1)
        self.entry_new_name = Gtk.Entry(text=self.original_vm["name"] + "_clone")
        self.entry_new_name.set_tooltip_text("Enter a name for the cloned VM")
        grid.attach(self.entry_new_name, 1, 0, 2, 1)
        grid.attach(Gtk.Label(label="New Folder:"), 0, 1, 1, 1)
        self.entry_new_path = Gtk.Entry()
        self.entry_new_path.set_tooltip_text("Select a directory for the cloned VM")
        btn = Gtk.Button(label="Browse")
        btn.set_tooltip_text("Choose a directory")
        btn.connect("clicked", self.on_browse)
        grid.attach(self.entry_new_path, 1, 1, 1, 1)
        grid.attach(btn, 2, 1, 1, 1)
        box.add(grid)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Clone", Gtk.ResponseType.OK)
        self.show_all()
    def on_browse(self, w):
        d = Gtk.FileChooserDialog(title="Select Folder", parent=self,
                                  action=Gtk.FileChooserAction.SELECT_FOLDER)
        d.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Select", Gtk.ResponseType.OK)
        if d.run() == Gtk.ResponseType.OK:
            self.entry_new_path.set_text(d.get_filename())
        d.destroy()
    def get_clone_info(self):
        return {"new_name": self.entry_new_name.get_text(), "new_path": self.entry_new_path.get_text()}

class ManageSnapshotsDialog(Gtk.Dialog):
    def __init__(self, parent, vm):
        super().__init__(title=f"Manage Snapshots for {vm['name']}", transient_for=parent)
        self.set_default_size(600, 400)
        self.set_resizable(True)
        self.vm = vm
        self.notebook = Gtk.Notebook()
        self.create_tab = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.create_tab.set_border_width(10)
        self.create_entry = Gtk.Entry()
        self.create_entry.set_placeholder_text("Enter new snapshot name")
        self.create_entry.set_tooltip_text("Enter snapshot name")
        create_btn = Gtk.Button(label="Create Snapshot")
        create_btn.set_tooltip_text("Create a new snapshot")
        create_btn.connect("clicked", self.on_create)
        self.list_current = Gtk.ListBox()
        self.list_current.set_selection_mode(Gtk.SelectionMode.NONE)
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self.list_current)
        self.create_tab.pack_start(self.create_entry, False, False, 0)
        self.create_tab.pack_start(create_btn, False, False, 0)
        self.create_tab.pack_start(Gtk.Label(label="Existing Snapshots:"), False, False, 5)
        self.create_tab.pack_start(scrolled, True, True, 0)
        self.restore_tab = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.restore_tab.set_border_width(10)
        self.restore_list = Gtk.ListBox()
        self.restore_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        restore_btn = Gtk.Button(label="Restore Selected Snapshot")
        restore_btn.connect("clicked", self.on_restore_clicked)
        self.restore_tab.pack_start(self.restore_list, True, True, 0)
        self.restore_tab.pack_end(restore_btn, False, False, 0)
        self.delete_tab = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.delete_tab.set_border_width(10)
        self.delete_list = Gtk.ListBox()
        self.delete_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        delete_btn = Gtk.Button(label="Delete Selected Snapshot")
        delete_btn.connect("clicked", self.on_delete_clicked)
        self.delete_tab.pack_start(self.delete_list, True, True, 0)
        self.delete_tab.pack_end(delete_btn, False, False, 0)
        self.notebook.append_page(self.create_tab, Gtk.Label(label="Create / View"))
        self.notebook.append_page(self.restore_tab, Gtk.Label(label="Restore"))
        self.notebook.append_page(self.delete_tab, Gtk.Label(label="Delete"))
        self.get_content_area().add(self.notebook)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.notebook.connect("switch-page", self.on_switch)
        self.refresh_all_lists()
        self.show_all()
    def on_switch(self, notebook, page, page_num):
        self.refresh_all_lists()
    def refresh_all_lists(self):
        snaps = list_snapshots(self.vm)
        for listbox in [self.list_current, self.restore_list, self.delete_list]:
            for child in listbox.get_children(): listbox.remove(child)
            for snap in snaps:
                row = Gtk.ListBoxRow()
                row.add(Gtk.Label(label=snap, xalign=0.05, margin=5))
                listbox.add(row)
            listbox.show_all()
    def handle_operation(self, operation_func, *args):
        progress = ProgressDialog(self, "Processing Snapshot...")
        def task_thread():
            def pulse_loop():
                while not stop_pulse:
                    GLib.idle_add(progress.pulse, "Processing...")
                    time.sleep(0.2)
            import time
            stop_pulse = False
            pulse_thread = threading.Thread(target=pulse_loop, daemon=True)
            pulse_thread.start()
            success, message = operation_func(*args)
            stop_pulse = True
            GLib.idle_add(progress.destroy)
            if success:
                GLib.idle_add(show_info_dialog, "Success", message, self)
                GLib.idle_add(self.refresh_all_lists)
            else:
                GLib.idle_add(show_detailed_error_dialog, "Snapshot Operation Failed", message, self)
        threading.Thread(target=task_thread, daemon=True).start()
        progress.run()
    def on_create(self, button):
        snap_name = self.create_entry.get_text().strip()
        if snap_name:
            self.handle_operation(create_snapshot_cmd, self.vm, snap_name)
            self.create_entry.set_text("")
    def on_restore_clicked(self, button):
        row = self.restore_list.get_selected_row()
        if row:
            snap = row.get_child().get_text()
            self.handle_operation(restore_snapshot_cmd, self.vm, snap)
    def on_delete_clicked(self, button):
        row = self.delete_list.get_selected_row()
        if row:
            snap = row.get_child().get_text()
            d = Gtk.MessageDialog(transient_for=self, flags=0, message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.YES_NO, text=f"Delete snapshot '{snap}'?")
            if d.run() == Gtk.ResponseType.YES:
                self.handle_operation(delete_snapshot_cmd, self.vm, snap)
            d.destroy()

class QEMUManagerMain(Gtk.Window):
    def __init__(self):
        super().__init__(title="Nicos Qemu GUI")
        self.set_default_size(1000,700)
        self.set_resizable(True)
        self.vm_processes = {}
        self.vm_configs = load_all_vm_configs()
        self.build_ui()
        self.apply_css()
    def build_ui(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(0)
        vbox.set_margin_bottom(0)
        vbox.set_margin_start(0)
        vbox.set_margin_end(0)
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        self.set_titlebar(header)
        btn_add = Gtk.Button(label="+")
        btn_add.set_tooltip_text("Create a new virtual machine")
        btn_add.connect("clicked", self.on_add_vm)
        header.pack_end(btn_add)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self.listbox)
        vbox.pack_start(scrolled, True, True, 0)
        self.add(vbox)
        self.refresh_vm_list()
    def apply_css(self):
        css = b"""
        window { background-color: #1e1e2e; }
        .vm-item { background-color: #2c2c3c; border-radius: 8px; padding: 12px; margin: 4px; color: #ffffff; box-shadow: 0 2px 4px rgba(0,0,0,0.2); }
        .round-button { border-radius: 50%; padding: 4px; background-color: transparent; }
        .iso-drop-area { background-color: #3b3b4b; border: 2px dashed #ffffff; }
        """
        sp = Gtk.CssProvider()
        sp.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), sp, Gtk.STYLE_PROVIDER_PRIORITY_USER)
    def on_add_vm(self, w):
        d = ISOSelectDialog(self)
        d.show_all()
    def add_vm(self, config):
        if config is None:
            return
        save_vm_config(config)
        index = load_vm_index()
        if config["path"] not in index:
            index.append(config["path"])
            save_vm_index(index)
        self.vm_configs = load_all_vm_configs()
        self.refresh_vm_list()
    def refresh_vm_list(self):
        for row in self.listbox.get_children():
            self.listbox.remove(row)
        self.vm_configs.sort(key=lambda x: x.get('name', '').lower())
        for vm in self.vm_configs:
            row = self.create_vm_row(vm)
            self.listbox.add(row)
        self.listbox.show_all()
    def create_vm_row(self, vm):
        row = Gtk.ListBoxRow()
        event_box = Gtk.EventBox()
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        hbox.get_style_context().add_class("vm-item")
        label = Gtk.Label(label=vm["name"], xalign=0.0)
        hbox.pack_start(label, True, True, 0)
        play_btn = Gtk.Button()
        play_btn.set_relief(Gtk.ReliefStyle.NONE)
        play_img = Gtk.Image.new_from_icon_name("media-playback-start", Gtk.IconSize.BUTTON)
        play_btn.set_image(play_img)
        play_btn.get_style_context().add_class("round-button")
        play_btn.set_tooltip_text("Start virtual machine")
        play_btn.connect("clicked", lambda b, v=vm: self.start_vm(v))
        settings_btn = Gtk.Button()
        settings_btn.set_relief(Gtk.ReliefStyle.NONE)
        set_img = Gtk.Image.new_from_icon_name("preferences-system", Gtk.IconSize.BUTTON)
        settings_btn.set_image(set_img)
        settings_btn.get_style_context().add_class("round-button")
        settings_btn.set_tooltip_text("Edit VM settings")
        settings_btn.connect("clicked", lambda b, v=vm: self.edit_vm(v))
        hbox.pack_end(settings_btn, False, False, 0)
        hbox.pack_end(play_btn, False, False, 0)
        event_box.add(hbox)
        event_box.connect("button-press-event", self.on_vm_item_event, vm)
        row.add(event_box)
        return row
    def on_vm_item_event(self, widget, event, vm):
        if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == 1:
            self.start_vm(vm)
            return True
        if event.button == 3:
            menu = self.create_context_menu(vm)
            menu.popup_at_pointer(event)
            return True
        return False
    def create_context_menu(self, vm):
        menu = Gtk.Menu()
        items = {"Start": self.start_vm, "Edit": self.edit_vm,
                 "Manage Snapshots": self.open_manage_snapshots, "Clone": self.clone_vm,
                 "Delete": self.delete_vm}
        for label, func in items.items():
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda w, v=vm, f=func: f(v))
            menu.append(item)
        menu.show_all()
        return menu
    def open_manage_snapshots(self, vm):
        if vm.get("disk_type") != "qcow2":
            show_detailed_error_dialog("Snapshots not supported", "Snapshots are only available for 'qcow2' disk images.", self)
            return
        dlg = ManageSnapshotsDialog(self, vm)
        dlg.run()
        dlg.destroy()
    def start_vm(self, vm):
        if not vm.get("launch_cmd"):
            show_detailed_error_dialog("No start command!", "Launch command is missing or invalid. Please check VM settings.", self)
            logging.error(f"No launch command for VM {vm['name']}")
            return
        if not validate_vm_config(vm):
            return
        try:
            proc = subprocess.Popen(vm["launch_cmd"])
            self.vm_processes[vm['name']] = proc
            logging.info(f"Started VM {vm['name']} with PID {proc.pid}")
        except (OSError, FileNotFoundError) as e:
            show_detailed_error_dialog(f"Error starting Virtual Machine: {e}", str(e), self)
            logging.error(f"Error starting VM {vm['name']}: {e}")
    def edit_vm(self, vm):
        dialog = VMSettingsDialog(self, vm)
        if dialog.run() == Gtk.ResponseType.OK:
            updated_config = dialog.get_updated_config()
            if updated_config:
                save_vm_config(updated_config)
                self.vm_configs = load_all_vm_configs()
                self.refresh_vm_list()
        dialog.destroy()
    def delete_vm(self, vm):
        dialog = Gtk.MessageDialog(transient_for=self, flags=0, message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.YES_NO, text=f"Delete '{vm['name']}'?")
        dialog.set_secondary_text("This will permanently delete the VM's configuration and disk image. This action cannot be undone.")
        resp = dialog.run()
        dialog.destroy()
        if resp == Gtk.ResponseType.YES:
            try:
                vm_path = vm["path"]
                conf_file = os.path.join(vm_path, f"{vm['name']}.json")
                if os.path.exists(conf_file): os.remove(conf_file)
                if os.path.exists(vm["disk_image"]): os.remove(vm["disk_image"])
                delete_ovmf_dir(vm)
                tpm_dir = os.path.join(vm_path, "tpm")
                if os.path.exists(tpm_dir): shutil.rmtree(tpm_dir)
                index = load_vm_index()
                if vm_path in index and not any(f.endswith(".json") for f in os.listdir(vm_path)):
                    index.remove(vm_path)
                    save_vm_index(index)
                self.vm_configs = load_all_vm_configs()
                self.refresh_vm_list()
            except OSError as e:
                show_detailed_error_dialog(f"Error deleting VM: {e}", str(e), self)
    def clone_vm(self, vm):
        clone_dialog = VMCloneDialog(self, vm)
        if clone_dialog.run() == Gtk.ResponseType.OK:
            clone_info = clone_dialog.get_clone_info()
            if not clone_info or not clone_info["new_name"] or not clone_info["new_path"]:
                show_detailed_error_dialog("Invalid Clone Info", "New name and path cannot be empty.", self)
                clone_dialog.destroy()
                return

            progress = ProgressDialog(self, f"Cloning {vm['name']}...")
            def clone_thread():
                new_vm_name = clone_info["new_name"]
                new_vm_path = clone_info["new_path"]
                if re.search(r'[<>:"/\\|?*]', new_vm_name):
                    GLib.idle_add(show_detailed_error_dialog, "Invalid clone name.", "Name cannot contain special characters.", self)
                    GLib.idle_add(progress.destroy)
                    return
                os.makedirs(new_vm_path, exist_ok=True)
                if not os.access(new_vm_path, os.W_OK):
                    GLib.idle_add(show_detailed_error_dialog, "Invalid clone directory.", "Directory is not writable.", self)
                    GLib.idle_add(progress.destroy)
                    return

                new_vm_config = vm.copy()
                new_vm_config["name"] = new_vm_name
                new_vm_config["path"] = new_vm_path
                new_vm_config["disk_image"] = os.path.join(new_vm_path, f"{new_vm_name}.img")
                try:
                    source_size = os.path.getsize(vm["disk_image"])
                    copied = 0
                    with open(vm["disk_image"], 'rb') as fsrc, open(new_vm_config["disk_image"], 'wb') as fdst:
                        while True:
                            buf = fsrc.read(4 * 1024 * 1024)
                            if not buf: break
                            fdst.write(buf)
                            copied += len(buf)
                            fraction = copied / source_size
                            GLib.idle_add(progress.update, fraction, f"{int(fraction*100)}%")

                    if vm["firmware"] in ["UEFI", "UEFI+Secure Boot"]:
                        copy_uefi_files(new_vm_config, self)

                    new_vm_config["launch_cmd"] = build_launch_command(new_vm_config)
                    save_vm_config(new_vm_config)

                    index = load_vm_index()
                    if new_vm_path not in index:
                        index.append(new_vm_path)
                        save_vm_index(index)

                    GLib.idle_add(self.add_vm, new_vm_config)
                except (OSError, subprocess.CalledProcessError) as e:
                    GLib.idle_add(show_detailed_error_dialog, f"Error cloning VM: {e}", str(e), self)
                finally:
                    GLib.idle_add(progress.destroy)

            threading.Thread(target=clone_thread, daemon=True).start()
            progress.run()
        clone_dialog.destroy()

if __name__ == "__main__":
    win = QEMUManagerMain()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
