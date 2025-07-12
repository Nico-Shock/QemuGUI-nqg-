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
        "/usr/share/ovmf",
        "/usr/share/edk2"
    ]
    for d in candidates:
        if os.path.isdir(d):
            files = os.listdir(d)
            if any(f.startswith("OVMF_CODE") for f in files):
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
    dialog = LoadingDialog(parent_window)
    def copy_thread():
        host_os = get_host_os()
        ovmf_dir = os.path.join(config["path"], "ovmf")
        os.makedirs(ovmf_dir, exist_ok=True)
        src_dir = find_ovmf_source_dir()
        if not src_dir:
            GLib.idle_add(show_detailed_error_dialog, "OVMF folder not found.", "No valid OVMF source directory detected.", parent_window)
            GLib.idle_add(dialog.destroy)
            return False
        firmware = config.get("firmware", "")
        if host_os == "arch":
            if firmware == "UEFI":
                files = ["OVMF_CODE_4M.fd"]
            elif firmware == "UEFI+Secure Boot":
                files = ["OVMF_CODE_4M.fd", "OVMF_VARS_4M.fd"]
            else:
                files = []
        else:
            if firmware == "UEFI":
                files = ["OVMF_CODE.fd"]
            elif firmware == "UEFI+Secure Boot":
                files = ["OVMF_CODE.fd", "OVMF_VARS.fd"]
            else:
                files = []
        for f in files:
            src = os.path.join(src_dir, f)
            dst = os.path.join(ovmf_dir, f)
            if os.path.exists(src):
                try:
                    shutil.copy(src, dst)
                    logging.info(f"Copied {src} to {dst}")
                except Exception as e:
                    logging.error(f"Copy failed {src} to {dst}: {e}")
                    pwd = prompt_sudo_password(parent_window)
                    if pwd:
                        cmd = f"echo {pwd} | sudo -S cp '{src}' '{dst}'"
                        subprocess.run(cmd, shell=True)
            else:
                logging.warning(f"Source file {src} does not exist.")
        # Set config paths based on copied files
        if firmware == "UEFI":
            if host_os == "arch":
                config["ovmf_code"] = os.path.join(ovmf_dir, "OVMF_CODE_4M.fd")
            else:
                config["ovmf_code"] = os.path.join(ovmf_dir, "OVMF_CODE.fd")
        elif firmware == "UEFI+Secure Boot":
            if host_os == "arch":
                config["ovmf_code_secure"] = os.path.join(ovmf_dir, "OVMF_CODE_4M.fd")
                config["ovmf_vars_secure"] = os.path.join(ovmf_dir, "OVMF_VARS_4M.fd")
            else:
                config["ovmf_code_secure"] = os.path.join(ovmf_dir, "OVMF_CODE.fd")
                config["ovmf_vars_secure"] = os.path.join(ovmf_dir, "OVMF_VARS.fd")
        GLib.idle_add(dialog.destroy)
        return True
    threading.Thread(target=copy_thread, daemon=True).start()
    dialog.run()
    return True

def delete_ovmf_dir(config):
    d = os.path.join(config["path"], "ovmf")
    if os.path.exists(d):
        try:
            shutil.rmtree(d)
            logging.info(f"Deleted {d}")
            return True
        except OSError:
            show_detailed_error_dialog("Error deleting OVMF folder.", "", None)
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
            show_detailed_error_dialog("Secure Boot files missing.", "", None)
            return False
    if vm.get("iso_enabled") and vm.get("iso") and not os.path.exists(urllib.parse.unquote(vm["iso"])):
        show_detailed_error_dialog("ISO file missing.", vm["iso"], None)
        return False
    if vm.get("tpm_enabled"):
        if not shutil.which("swtpm"):
            show_detailed_error_dialog("TPM emulator not found.", "", None)
            return False
    return True

def build_launch_command(config):
    host = get_host_os()
    arch = config.get("arch", "x86_64")
    qemu = shutil.which(f"qemu-system-{arch}")
    if not qemu:
        show_detailed_error_dialog("QEMU not found!", "", None)
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
        cmd += ["-cdrom", urllib.parse.unquote(config["iso"])]
    if config["firmware"] == "UEFI" and config.get("ovmf_code"):
        cmd += ["-drive", f"if=pflash,format=raw,readonly=on,file={config['ovmf_code']}"]
    if config["firmware"] == "UEFI+Secure Boot":
        cmd += ["-drive", f"if=pflash,format=raw,readonly=on,file={config.get('ovmf_code_secure','')}", "-drive", f"if=pflash,format=raw,file={config.get('ovmf_vars_secure','')}"]
    if config.get("tpm_enabled"):
        tpm_dir = os.path.join(config["path"], "tpm")
        os.makedirs(tpm_dir, exist_ok=True)
        sock = os.path.join(tpm_dir, "swtpm-sock")
        subprocess.Popen(["swtpm", "socket", "--tpm2", "--tpmstate", f"dir={tpm_dir}", "--ctrl", f"type=unixio,path={sock}", "--log", "level=0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cmd += ["-chardev", f"socket,id=chrtpm,path={sock}", "-tpmdev", "emulator,id=tpm0,chardev=chrtpm", "-device", "tpm-tis,tpmdev=tpm0"]
    logging.info("Built launch command: " + " ".join(cmd))
    return cmd

def list_snapshots(vm):
    qi = shutil.which("qemu-img")
    if not qi or not os.path.exists(vm["disk_image"]):
        return []
    try:
        out = subprocess.check_output([qi, "snapshot", "-l", vm["disk_image"]], universal_newlines=True, stderr=subprocess.DEVNULL)
        snaps = [line.split()[1] for line in out.splitlines()[2:] if line and line.split()[0].isdigit()]
        return snaps
    except:
        return []

def create_snapshot_cmd(vm, snap_name):
    qi = shutil.which("qemu-img")
    if not qi or not snap_name or re.search(r'[<>:"/\\|?*]', snap_name):
        return False
    try:
        subprocess.run([qi, "snapshot", "-c", snap_name, vm["disk_image"]], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except:
        return False

def restore_snapshot(vm, snap_name):
    qi = shutil.which("qemu-img")
    if not qi:
        return False
    try:
        subprocess.run([qi, "snapshot", "-a", snap_name, vm["disk_image"]], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except:
        return False

def delete_snapshot(vm, snap_name):
    qi = shutil.which("qemu-img")
    if not qi:
        return False
    try:
        subprocess.run([qi, "snapshot", "-d", snap_name, vm["disk_image"]], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except:
        return False

def load_vm_index():
    if os.path.exists(CONFIG_FILE) and os.path.getsize(CONFIG_FILE) > 0:
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except:
            return []
    return []

def save_vm_index(index):
    with open(CONFIG_FILE, "w") as f:
        json.dump(index, f, indent=4)

def load_all_vm_configs():
    configs = []
    for p in load_vm_index():
        for fn in os.listdir(p):
            if fn.endswith(".json"):
                with open(os.path.join(p, fn)) as f:
                    configs.append(json.load(f))
                break
    return configs

def save_vm_config(config):
    fn = os.path.join(config["path"], config["name"] + ".json")
    with open(fn, "w") as f:
        json.dump(config, f, indent=4)

def prompt_sudo_password(parent):
    d = Gtk.Dialog(title="Sudo Password", transient_for=parent, flags=0)
    d.add_buttons("OK", Gtk.ResponseType.OK, "Cancel", Gtk.ResponseType.CANCEL)
    box = d.get_content_area()
    box.add(Gtk.Label("Enter Sudo password:"))
    e = Gtk.Entry()
    e.set_visibility(False)
    box.add(e)
    d.show_all()
    resp = d.run()
    pwd = e.get_text() if resp == Gtk.ResponseType.OK else None
    d.destroy()
    return pwd

def show_detailed_error_dialog(message, details, parent):
    dlg = Gtk.Dialog(title="Error", transient_for=parent, flags=0)
    dlg.add_button("OK", Gtk.ResponseType.OK)
    box = dlg.get_content_area()
    box.set_spacing(10)
    box.add(Gtk.Label(label=message))
    exp = Gtk.Expander(label="Details")
    exp.set_expanded(False)
    exp_content = Gtk.Label(label=details)
    exp.add(exp_content)
    box.add(exp)
    dlg.show_all()
    dlg.run()
    dlg.destroy()

class LoadingDialog(Gtk.Dialog):
    def __init__(self, parent, msg="Processing..."):
        super().__init__(title="Wait", transient_for=parent)
        self.set_modal(True)
        self.set_default_size(300,100)
        box = self.get_content_area()
        box.add(Gtk.Label(msg))
        self.progress = Gtk.ProgressBar()
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
            self.iso_chosen(uris[0].replace("file://", "").strip())
    def on_skip_clicked(self, w):
        self.destroy()
        d = VMCreateDialog(self.parent)
        if d.run() == Gtk.ResponseType.OK:
            self.parent.add_vm(d.get_vm_config())
        d.destroy()
    def iso_chosen(self, iso_path):
        self.destroy()
        d = VMCreateDialog(self.parent, iso_path)
        if d.run() == Gtk.ResponseType.OK:
            self.parent.add_vm(d.get_vm_config())
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
        grid.attach(Gtk.Label(label="Architecture:"), 0, 10, 1, 1)
        self.combo_arch = Gtk.ComboBoxText()
        for arch in ["x86_64", "aarch64", "riscv64"]:
            self.combo_arch.append_text(arch)
        self.combo_arch.set_active(0)
        self.combo_arch.set_tooltip_text("Select CPU architecture")
        grid.attach(self.combo_arch, 1, 10, 2, 1)
        box.add(grid)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Create", Gtk.ResponseType.OK)
        self.show_all()
        self.on_display_changed(self.combo_disp)
        self.initial_firmware = "BIOS"
        if self.radio_uefi.get_active():
            self.initial_firmware = "UEFI"
        elif self.radio_secure.get_active():
            self.initial_firmware = "UEFI+Secure Boot"

    def on_display_changed(self, combo):
        selected = combo.get_active_text()
        if selected == "gtk (default)":
            self.recommend_label.set_text("Recommended for Linux")
            self.check_3d.set_sensitive(True)
        elif selected == "sdl":
            self.recommend_label.set_text("Recommended for Linux")
            self.check_3d.set_sensitive(True)
        elif selected == "spice (virtio)":
            self.recommend_label.set_text("Recommended for Windows")
            self.check_3d.set_sensitive(True)
        elif selected == "virtio":
            self.recommend_label.set_text("Optimized for Windows with 3D")
            self.check_3d.set_sensitive(True)
        elif selected == "qemu":
            self.recommend_label.set_text("")
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
        if not path or not os.path.isdir(path) or not os.access(path, os.W_OK):
            show_detailed_error_dialog("Invalid directory.", "Directory does not exist or is not writable.", self)
            logging.error(f"Invalid directory: {path}")
            return None
        total_mem = psutil.virtual_memory().total // (1024 * 1024)
        ram = self.spin_ram.get_value_as_int()
        if ram > total_mem:
            show_detailed_error_dialog("Invalid RAM.", f"RAM ({ram} MiB) exceeds available memory ({total_mem} MiB).", self)
            logging.error(f"RAM {ram} MiB exceeds available {total_mem} MiB")
            return None
        firmware = "BIOS"
        if self.radio_uefi.get_active():
            firmware = "UEFI"
        elif self.radio_secure.get_active():
            firmware = "UEFI+Secure Boot"
        config = {
            "name": name,
            "path": path,
            "cpu": self.spin_cpu.get_value_as_int(),
            "ram": ram,
            "disk": self.spin_disk.get_value_as_int(),
            "disk_type": "qcow2" if self.radio_qcow2.get_active() else "raw",
            "firmware": firmware,
            "display": self.combo_disp.get_active_text(),
            "iso": self.iso_path if self.iso_path else "",
            "iso_enabled": True if self.iso_path else False,
            "3d_acceleration": self.check_3d.get_active(),
            "disk_image": os.path.join(path, name + ".img"),
            "tpm_enabled": self.check_tpm.get_active(),
            "arch": self.combo_arch.get_active_text()
        }
        if not os.path.exists(config["disk_image"]):
            qemu_img = shutil.which("qemu-img")
            if qemu_img:
                try:
                    subprocess.run([qemu_img, "create", "-f", config["disk_type"],
                                   config["disk_image"], f"{config['disk']}G"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    logging.info(f"Created disk image {config['disk_image']}")
                except subprocess.CalledProcessError as e:
                    show_detailed_error_dialog(f"Error creating disk: {e}", str(e), self)
                    logging.error(f"Error creating disk {config['disk_image']}: {e}")
                    return None
            else:
                show_detailed_error_dialog("qemu-img not found.", "Please install QEMU.", self)
                logging.error("qemu-img not found for disk creation")
                return None
        if config["firmware"] in ["UEFI", "UEFI+Secure Boot"]:
            if not copy_uefi_files(config, self):
                show_detailed_error_dialog("Failed to copy UEFI files. Using BIOS firmware.", "Check OVMF installation.", self)
                logging.warning("Failed to copy UEFI files, falling back to BIOS")
                config["firmware"] = "BIOS"
        elif self.initial_firmware in ["UEFI", "UEFI+Secure Boot"]:
            delete_ovmf_dir(config)
        config["launch_cmd"] = build_launch_command(config)
        return config

class VMSettingsDialog(Gtk.Dialog):
    def __init__(self, parent, config):
        super().__init__(title="Edit Virtual Machine Settings", transient_for=parent)
        self.set_default_size(500,450)
        self.set_resizable(True)
        self.config = config.copy()
        self.original_name = config["name"]
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
        grid.attach(self.entry_name, 1, 0, 2, 1)
        grid.attach(Gtk.Label(label="ISO Path:"), 0, 1, 1, 1)
        self.check_iso_enable = Gtk.CheckButton(label="Enable ISO")
        self.check_iso_enable.set_active(self.config.get("iso_enabled", False))
        self.check_iso_enable.set_tooltip_text("Enable or disable ISO usage")
        self.check_iso_enable.connect("toggled", self.on_iso_enabled_toggled_settings)
        grid.attach(self.check_iso_enable, 1, 1, 1, 1)
        self.entry_iso = Gtk.Entry()
        self.entry_iso.set_text(self.config.get("iso", ""))
        self.entry_iso.set_tooltip_text("Path to the ISO file")
        grid.attach(self.entry_iso, 2, 1, 1, 1)
        self.btn_iso_browse = Gtk.Button(label="Browse")
        self.btn_iso_browse.set_tooltip_text("Select a new ISO file")
        self.btn_iso_browse.connect("clicked", self.on_iso_browse)
        grid.attach(self.btn_iso_browse, 3, 1, 1, 1)
        grid.attach(Gtk.Label(label="CPU Cores:"), 0, 2, 1, 1)
        self.spin_cpu = Gtk.SpinButton.new_with_range(1, os.cpu_count(), 1)
        self.spin_cpu.set_value(self.config.get("cpu", 2))
        self.spin_cpu.set_tooltip_text("Number of CPU cores for the VM")
        grid.attach(self.spin_cpu, 1, 2, 2, 1)
        grid.attach(Gtk.Label(label=f"Max: {os.cpu_count()}"), 3, 2, 1, 1)
        grid.attach(Gtk.Label(label="RAM (MiB):"), 0, 3, 1, 1)
        self.spin_ram = Gtk.SpinButton.new_with_range(256, 131072, 256)
        self.spin_ram.set_value(self.config.get("ram", 4096))
        self.spin_ram.set_tooltip_text("Memory allocation in MiB")
        grid.attach(self.spin_ram, 1, 3, 2, 1)
        grid.attach(Gtk.Label(label="Max: 131072 MiB"), 3, 3, 1, 1)
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
        if self.config.get("firmware", "BIOS") == "UEFI":
            self.radio_uefi.set_active(True)
        elif self.config.get("firmware") == "UEFI+Secure Boot":
            self.radio_secure.set_active(True)
        else:
            self.radio_bios.set_active(True)
        grid.attach(fw_box, 1, 4, 2, 1)
        grid.attach(Gtk.Label(label="Enable TPM:"), 0, 5, 1, 1)
        self.check_tpm = Gtk.CheckButton()
        self.check_tpm.set_active(self.config.get("tpm_enabled", False))
        self.check_tpm.set_tooltip_text("Enable Trusted Platform Module")
        grid.attach(self.check_tpm, 1, 5, 2, 1)
        grid.attach(Gtk.Label(label="Display:"), 0, 6, 1, 1)
        self.combo_disp = Gtk.ComboBoxText()
        for opt in ["gtk (default)", "sdl", "spice (virtio)", "virtio", "qemu"]:
            self.combo_disp.append_text(opt)
        active_index = 0
        if self.config.get("display") in ["gtk (default)", "sdl", "spice (virtio)", "virtio", "qemu"]:
            active_index = ["gtk (default)", "sdl", "spice (virtio)", "virtio", "qemu"].index(self.config.get("display"))
        self.combo_disp.set_active(active_index)
        self.combo_disp.set_tooltip_text("Select display backend")
        grid.attach(self.combo_disp, 1, 6, 2, 1)
        self.recommend_label = Gtk.Label()
        grid.attach(self.recommend_label, 3, 6, 1, 1)
        self.combo_disp.connect("changed", self.on_display_changed)
        grid.attach(Gtk.Label(label="3D Acceleration:"), 0, 7, 1, 1)
        self.check_3d = Gtk.CheckButton()
        self.check_3d.set_active(self.config.get("3d_acceleration", False))
        self.check_3d.set_tooltip_text("Enable 3D graphics acceleration")
        grid.attach(self.check_3d, 1, 7, 2, 1)
        grid.attach(Gtk.Label(label="Architecture:"), 0, 8, 1, 1)
        self.combo_arch = Gtk.ComboBoxText()
        for arch in ["x86_64", "aarch64", "riscv64"]:
            self.combo_arch.append_text(arch)
        active_arch_index = 0
        if self.config.get("arch") in ["x86_64", "aarch64", "riscv64"]:
            active_arch_index = ["x86_64", "aarch64", "riscv64"].index(self.config.get("arch"))
        self.combo_arch.set_active(active_arch_index)
        self.combo_arch.set_tooltip_text("Select CPU architecture")
        grid.attach(self.combo_arch, 1, 8, 2, 1)
        box.add(grid)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Apply", Gtk.ResponseType.OK)
        self.show_all()
        self.on_display_changed(self.combo_disp)
        self.initial_firmware = self.config.get("firmware", "BIOS")
        self.update_iso_entry_sensitivity_settings()

    def on_display_changed(self, combo):
        selected = combo.get_active_text()
        if selected == "gtk (default)":
            self.recommend_label.set_text("Recommended for Linux")
            self.check_3d.set_sensitive(True)
        elif selected == "sdl":
            self.recommend_label.set_text("Recommended for Linux")
            self.check_3d.set_sensitive(True)
        elif selected == "spice (virtio)":
            self.recommend_label.set_text("Recommended for Windows")
            self.check_3d.set_sensitive(True)
        elif selected == "virtio":
            self.recommend_label.set_text("Optimized for Windows with 3D")
            self.check_3d.set_sensitive(True)
        elif selected == "qemu":
            self.recommend_label.set_text("")
            self.check_3d.set_sensitive(False)
            self.check_3d.set_active(False)

    def on_iso_enabled_toggled_settings(self, check):
        self.update_iso_entry_sensitivity_settings()

    def update_iso_entry_sensitivity_settings(self):
        is_enabled = self.check_iso_enable.get_active()
        self.entry_iso.set_sensitive(is_enabled)
        self.btn_iso_browse.set_sensitive(is_enabled)

    def on_iso_browse(self, w):
        d = Gtk.FileChooserDialog(title="Select ISO File", parent=self,
                                  action=Gtk.FileChooserAction.OPEN)
        d.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        f = Gtk.FileFilter()
        f.set_name("ISO Files")
        f.add_pattern("*.iso")
        d.add_filter(f)
        if d.run() == Gtk.ResponseType.OK:
            self.entry_iso.set_text(d.get_filename())
        d.destroy()

    def get_updated_config(self):
        new_name = self.entry_name.get_text()
        if not new_name or re.search(r'[<>:"/\\|?*]', new_name):
            show_detailed_error_dialog("Invalid VM name.", "Name cannot be empty or contain special characters.", self)
            logging.error(f"Invalid VM name: {new_name}")
            return None
        total_mem = psutil.virtual_memory().total // (1024 * 1024)
        ram = self.spin_ram.get_value_as_int()
        if ram > total_mem:
            show_detailed_error_dialog("Invalid RAM.", f"RAM ({ram} MiB) exceeds available memory ({total_mem} MiB).", self)
            logging.error(f"RAM {ram} MiB exceeds available {total_mem} MiB")
            return None
        firmware = "BIOS"
        if self.radio_uefi.get_active():
            firmware = "UEFI"
        elif self.radio_secure.get_active():
            firmware = "UEFI+Secure Boot"
        if new_name != self.original_name:
            old_conf_file = os.path.join(self.config["path"], f"{self.original_name}.json")
            new_conf_file = os.path.join(self.config["path"], f"{new_name}.json")
            old_disk_image = self.config["disk_image"]
            new_disk_image = os.path.join(self.config["path"], f"{new_name}.img")
            try:
                if os.path.exists(old_conf_file):
                    os.rename(old_conf_file, new_conf_file)
                    logging.info(f"Renamed config from {old_conf_file} to {new_conf_file}")
                if os.path.exists(old_disk_image):
                    os.rename(old_disk_image, new_disk_image)
                    logging.info(f"Renamed disk image from {old_disk_image} to {new_disk_image}")
                self.config["disk_image"] = new_disk_image
            except OSError as e:
                show_detailed_error_dialog(f"Error renaming files: {e}", str(e), self)
                logging.error(f"Error renaming files: {e}")
                return None
        self.config["name"] = new_name
        self.config["iso"] = urllib.parse.unquote(self.entry_iso.get_text()) if self.check_iso_enable.get_active() else ""
        self.config["iso_enabled"] = self.check_iso_enable.get_active()
        self.config["cpu"] = self.spin_cpu.get_value_as_int()
        self.config["ram"] = ram
        self.config["firmware"] = firmware
        self.config["display"] = self.combo_disp.get_active_text()
        self.config["3d_acceleration"] = self.check_3d.get_active()
        self.config["tpm_enabled"] = self.check_tpm.get_active()
        self.config["arch"] = self.combo_arch.get_active_text()
        if self.config["firmware"] != self.initial_firmware:
            if self.config["firmware"] in ["UEFI", "UEFI+Secure Boot"]:
                if not copy_uefi_files(self.config, self):
                    show_detailed_error_dialog("Error copying UEFI files.", "Failed to copy OVMF files.", self)
                    logging.warning("Failed to copy UEFI files, falling back to BIOS")
                    self.config["firmware"] = "BIOS"
                    return None
            else:
                delete_ovmf_dir(self.config)
        self.config["launch_cmd"] = build_launch_command(self.config)
        return self.config

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
        super().__init__(title="Manage Snapshots", transient_for=parent)
        self.set_default_size(600, 400)
        self.set_resizable(True)
        self.vm = vm
        self.notebook = Gtk.Notebook()
        self.create_tab = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.create_tab.set_border_width(10)
        self.create_entry = Gtk.Entry()
        self.create_entry.set_tooltip_text("Enter snapshot name")
        create_btn = Gtk.Button(label="Create Snapshot")
        create_btn.set_tooltip_text("Create a new snapshot")
        create_btn.connect("clicked", self.on_create)
        self.create_list = Gtk.ListBox()
        self.create_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.create_tab.pack_start(self.create_entry, False, False, 0)
        self.create_tab.pack_start(create_btn, False, False, 0)
        self.create_tab.pack_start(self.create_list, True, True, 0)
        self.restore_tab = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.restore_tab.set_border_width(10)
        self.restore_list = Gtk.ListBox()
        self.restore_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.restore_list.connect("row-activated", self.on_restore)
        self.restore_tab.pack_start(self.restore_list, True, True, 0)
        self.delete_tab = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.delete_tab.set_border_width(10)
        self.delete_list = Gtk.ListBox()
        self.delete_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.delete_list.connect("row-activated", self.on_delete)
        self.delete_tab.pack_start(self.delete_list, True, True, 0)
        self.notebook.append_page(self.create_tab, Gtk.Label(label="Create"))
        self.notebook.append_page(self.restore_tab, Gtk.Label(label="Restore"))
        self.notebook.append_page(self.delete_tab, Gtk.Label(label="Delete"))
        self.get_content_area().add(self.notebook)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.notebook.connect("switch-page", self.on_switch)
        self.refresh_all()
        self.show_all()
    def on_switch(self, notebook, page, page_num):
        self.refresh_all()
    def refresh_all(self):
        self.refresh_list(self.create_list)
        self.refresh_list(self.restore_list)
        self.refresh_list(self.delete_list)
    def refresh_list(self, listbox):
        for child in listbox.get_children():
            listbox.remove(child)
        snaps = list_snapshots(self.vm)
        for snap in snaps:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=snap)
            row.add(label)
            listbox.add(row)
            row.show_all()
        listbox.show_all()
    def on_create(self, button):
        snap_name = self.create_entry.get_text()
        if snap_name:
            if create_snapshot_cmd(self.vm, snap_name):
                self.create_entry.set_text("")
                self.refresh_all()
            else:
                show_detailed_error_dialog("Failed to create snapshot.", "Check qemu-img and disk image.", self)
    def on_restore(self, listbox, row):
        snap = row.get_child().get_text()
        if restore_snapshot(self.vm, snap):
            show_detailed_error_dialog(f"Restored snapshot '{snap}'.", "", self)
            self.refresh_all()
        else:
            show_detailed_error_dialog("Failed to restore snapshot.", "Check qemu-img and disk image.", self)
    def on_delete(self, listbox, row):
        snap = row.get_child().get_text()
        d = Gtk.MessageDialog(transient_for=self, flags=0, message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.YES_NO, text=f"Delete snapshot '{snap}'?")
        response = d.run()
        d.destroy()
        if response == Gtk.ResponseType.YES:
            if delete_snapshot(self.vm, snap):
                self.refresh_all()
            else:
                show_detailed_error_dialog("Failed to delete snapshot.", "Check qemu-img and disk image.", self)

class QEMUManagerMain(Gtk.Window):
    def __init__(self):
        super().__init__(title="Nicos Qemu GUI")
        self.set_default_size(1000,700)
        self.set_resizable(True)
        self.vm_configs = load_all_vm_configs()
        self.build_ui()
        self.apply_css()
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
        .vm-item { background-color: #2c2c3c; border-radius: 8px; padding: 12px; margin: 4px; color: #ffffff; }
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
        for vm in self.vm_configs:
            row = self.create_vm_row(vm)
            self.listbox.add(row)
        self.listbox.show_all()
    def create_vm_row(self, vm):
        row = Gtk.ListBoxRow()
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
        play_btn.set_tooltip_text("Start virtual machine")
        play_btn.connect("clicked", lambda b, vm=vm: self.start_vm(vm))
        settings_btn = Gtk.Button()
        settings_btn.set_relief(Gtk.ReliefStyle.NONE)
        settings_btn.set_size_request(32,32)
        set_img = Gtk.Image.new_from_icon_name("preferences-system", Gtk.IconSize.BUTTON)
        settings_btn.set_image(set_img)
        settings_btn.get_style_context().add_class("round-button")
        settings_btn.set_tooltip_text("Edit VM settings")
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
            return True
        return False
    def create_context_menu(self, vm):
        menu = Gtk.Menu()
        item_start = Gtk.MenuItem(label="Start")
        item_start.set_tooltip_text("Start the virtual machine")
        item_settings = Gtk.MenuItem(label="Edit")
        item_settings.set_tooltip_text("Edit VM configuration")
        item_manage_snap = Gtk.MenuItem(label="Manage Snapshots")
        item_manage_snap.set_tooltip_text("Manage VM snapshots")
        item_delete = Gtk.MenuItem(label="Delete")
        item_delete.set_tooltip_text("Delete the virtual machine")
        item_clone = Gtk.MenuItem(label="Clone")
        item_clone.set_tooltip_text("Clone the virtual machine")
        item_start.connect("activate", lambda b, vm=vm: self.start_vm(vm))
        item_settings.connect("activate", lambda b, vm=vm: self.edit_vm(vm))
        item_manage_snap.connect("activate", lambda b, vm=vm: self.open_manage_snapshots(vm))
        item_delete.connect("activate", lambda b, vm=vm: self.delete_vm(vm))
        item_clone.connect("activate", lambda b, vm=vm: self.clone_vm(vm))
        menu.append(item_start)
        menu.append(item_settings)
        menu.append(item_manage_snap)
        menu.append(item_clone)
        menu.append(item_delete)
        menu.show_all()
        return menu
    def open_manage_snapshots(self, vm):
        dlg = ManageSnapshotsDialog(self, vm)
        dlg.run()
        dlg.destroy()
    def start_vm(self, vm):
        if not vm["launch_cmd"]:
            show_detailed_error_dialog("No start command!", "Launch command is missing.", self)
            logging.error(f"No launch command for VM {vm['name']}")
            return
        if not validate_vm_config(vm):
            return
        try:
            subprocess.Popen(vm["launch_cmd"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logging.info(f"Started VM {vm['name']}")
        except (subprocess.CalledProcessError, OSError) as e:
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
        dialog = Gtk.Dialog(title="Delete Virtual Machine?", transient_for=self, flags=0)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Delete", Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.add(Gtk.Label(label=f"Delete Virtual Machine '{vm['name']}' with all its files?"))
        dialog.show_all()
        resp = dialog.run()
        if resp == Gtk.ResponseType.OK:
            try:
                vm_path = vm["path"]
                conf_file = os.path.join(vm_path, f"{vm['name']}.json")
                if os.path.exists(conf_file):
                    os.remove(conf_file)
                    logging.info(f"Deleted config file {conf_file}")
                if os.path.exists(vm["disk_image"]):
                    os.remove(vm["disk_image"])
                    logging.info(f"Deleted disk image {vm['disk_image']}")
                delete_ovmf_dir(vm)
                tpm_dir = os.path.join(vm_path, "tpm")
                if os.path.exists(tpm_dir):
                    shutil.rmtree(tpm_dir)
                    logging.info(f"Deleted TPM directory {tpm_dir}")
                index = load_vm_index()
                if vm_path in index:
                    index.remove(vm_path)
                    save_vm_index(index)
                self.vm_configs = load_all_vm_configs()
                self.refresh_vm_list()
            except OSError as e:
                show_detailed_error_dialog(f"Error deleting Virtual Machine: {e}", str(e), self)
                logging.error(f"Error deleting VM {vm['name']}: {e}")
        dialog.destroy()
    def clone_vm(self, vm):
        clone_dialog = VMCloneDialog(self, vm)
        if clone_dialog.run() == Gtk.ResponseType.OK:
            clone_info = clone_dialog.get_clone_info()
            if clone_info:
                progress = ProgressDialog(self, "Cloning VM...")
                def clone_thread():
                    new_vm_name = clone_info["new_name"]
                    new_vm_path = clone_info["new_path"]
                    if not new_vm_path:
                        new_vm_path = os.path.join(os.path.dirname(vm["path"]), new_vm_name)
                    if not new_vm_name or re.search(r'[<>:"/\\|?*]', new_vm_name):
                        GLib.idle_add(show_detailed_error_dialog, "Invalid clone name.", "Name cannot be empty or contain special characters.", self)
                        GLib.idle_add(progress.destroy)
                        return
                    if not os.path.isdir(new_vm_path) or not os.access(new_vm_path, os.W_OK):
                        GLib.idle_add(show_detailed_error_dialog, "Invalid clone directory.", "Directory does not exist or is not writable.", self)
                        GLib.idle_add(progress.destroy)
                        return
                    new_vm_config = vm.copy()
                    new_vm_config["name"] = new_vm_name
                    new_vm_config["path"] = new_vm_path
                    new_vm_config["disk_image"] = os.path.join(new_vm_path, f"{new_vm_name}.img")
                    os.makedirs(new_vm_path, exist_ok=True)
                    try:
                        shutil.copy(vm["disk_image"], new_vm_config["disk_image"])
                        logging.info(f"Copied disk image from {vm['disk_image']} to {new_vm_config['disk_image']}")
                        if vm["firmware"] in ["UEFI", "UEFI+Secure Boot"]:
                            copy_uefi_files(new_vm_config, self)
                        save_vm_config(new_vm_config)
                        index = load_vm_index()
                        if new_vm_path not in index:
                            index.append(new_vm_path)
                            save_vm_index(index)
                        GLib.idle_add(self.add_vm, new_vm_config)
                    except (OSError, subprocess.CalledProcessError) as e:
                        GLib.idle_add(show_detailed_error_dialog, f"Error cloning VM: {e}", str(e), self)
                        logging.error(f"Error cloning VM {vm['name']} to {new_vm_name}: {e}")
                    GLib.idle_add(progress.destroy)
                threading.Thread(target=clone_thread, daemon=True).start()
                progress.run()
        clone_dialog.destroy()

if __name__ == "__main__":
    win = QEMUManagerMain()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
