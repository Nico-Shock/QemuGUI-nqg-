import os
import json
import subprocess
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib

CONFIG_DIR = "qemu_vms"
CONFIG_FILE = os.path.join(CONFIG_DIR, "vms.json")

class VMContextMenu(Gtk.Menu):
    def __init__(self, vm_name, parent):
        super().__init__()
        self.vm_name = vm_name
        self.parent = parent

        start_item = Gtk.MenuItem(label="Start")
        start_item.connect("activate", self.start_vm)
        self.append(start_item)

        power_menu = Gtk.Menu()
        power_item = Gtk.MenuItem(label="Power")
        power_item.set_submenu(power_menu)
        
        power_items = [
            ("Power Off", "system-shutdown"),
            ("Restart", "system-reboot"),
            ("Force Power Off", "dialog-error"),
            ("Force Restart", "dialog-warning"),
            ("Suspend", "system-suspend")
        ]
        
        for label, icon in power_items:
            item = Gtk.ImageMenuItem(label=label)
            img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU)
            item.set_image(img)
            item.connect("activate", self.power_action)
            power_menu.append(item)

        self.append(power_item)

        config_item = Gtk.MenuItem(label="Configure")
        config_item.connect("activate", self.configure_vm)
        self.append(config_item)

        self.show_all()

    def start_vm(self, widget):
        self.parent.start_vm(self.vm_name)

    def power_action(self, widget):
        action = widget.get_label().lower().replace(" ", "-")
        print(f"Performing: {action} on {self.vm_name}")

    def configure_vm(self, widget):
        self.parent.configure_vm(self.vm_name)

class VMConfigDialog(Gtk.Dialog):
    def __init__(self, parent, vm_name=None, config=None):
        super().__init__(title="VM Configuration", transient_for=parent)
        self.set_default_size(400, 300)
        
        self.os_list = self.get_os_list()
        self.config = config or {}
        self.vm_name = vm_name

        box = self.get_content_area()
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_margin(10)

        # Name
        lbl_name = Gtk.Label(label="VM Name:")
        self.entry_name = Gtk.Entry(text=self.config.get("name", ""))
        grid.attach(lbl_name, 0, 0, 1, 1)
        grid.attach(self.entry_name, 1, 0, 2, 1)

        # OS Detection
        lbl_os = Gtk.Label(label="Operating System:")
        self.os_combo = Gtk.ComboBoxText()
        for os_name in self.os_list:
            self.os_combo.append_text(os_name)
        grid.attach(lbl_os, 0, 1, 1, 1)
        grid.attach(self.os_combo, 1, 1, 2, 1)

        # Hardware
        lbl_cpu = Gtk.Label(label="CPU Cores:")
        self.entry_cpu = Gtk.SpinButton.new_with_range(1, 32, 1)
        self.entry_cpu.set_value(self.config.get("cpu", 2))
        grid.attach(lbl_cpu, 0, 2, 1, 1)
        grid.attach(self.entry_cpu, 1, 2, 1, 1)

        lbl_ram = Gtk.Label(label="RAM (GB):")
        self.entry_ram = Gtk.SpinButton.new_with_range(1, 128, 1)
        self.entry_ram.set_value(self.config.get("ram", 4))
        grid.attach(lbl_ram, 0, 3, 1, 1)
        grid.attach(self.entry_ram, 1, 3, 1, 1)

        # Storage
        lbl_disk = Gtk.Label(label="Disk Size (GB):")
        self.entry_disk = Gtk.SpinButton.new_with_range(10, 1000, 10)
        self.entry_disk.set_value(self.config.get("disk", 50))
        grid.attach(lbl_disk, 0, 4, 1, 1)
        grid.attach(self.entry_disk, 1, 4, 1, 1)

        # Display
        lbl_display = Gtk.Label(label="Display Type:")
        self.display_combo = Gtk.ComboBoxText()
        displays = ["SDL", "GTK", "QXL (Recommended)", "VirtIO", "Spice"]
        for d in displays:
            self.display_combo.append_text(d)
        self.display_combo.set_active(0)
        grid.attach(lbl_display, 0, 5, 1, 1)
        grid.attach(self.display_combo, 1, 5, 2, 1)

        # 3D Acceleration
        self.accel_switch = Gtk.Switch()
        self.accel_switch.set_active(self.config.get("3d_accel", False))
        grid.attach(Gtk.Label(label="3D Acceleration:"), 0, 6, 1, 1)
        grid.attach(self.accel_switch, 1, 6, 1, 1)

        box.add(grid)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Create", Gtk.ResponseType.OK)

    def get_os_list(self):
        try:
            output = subprocess.check_output(["quickget", "--list"], text=True)
            return [line.split()[0] for line in output.splitlines()[2:]]
        except:
            return ["ubuntu", "windows", "debian", "fedora"]

class MainWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="QEMU Manager")
        self.set_default_size(800, 600)
        self.vm_configs = self.load_config()
        
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        
        # Header
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        self.set_titlebar(header)

        # Add VM Button
        add_btn = Gtk.Button()
        add_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        add_box.pack_start(Gtk.Label(label="+", halign=Gtk.Align.CENTER), True, True, 0)
        add_btn.add(add_box)
        add_btn.connect("clicked", self.show_create_dialog)
        header.pack_end(add_btn)

        # VM List
        self.flowbox = Gtk.FlowBox()
        self.flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flowbox.set_max_children_per_line(4)
        self.refresh_vm_list()
        
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self.flowbox)
        main_box.add(scrolled)

        self.add(main_box)
        self.show_all()

    def refresh_vm_list(self):
        for child in self.flowbox.get_children():
            self.flowbox.remove(child)
        
        for vm in self.vm_configs:
            frame = Gtk.Frame(label=vm["name"])
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.set_margin(10)
            
            lbl_os = Gtk.Label(label=f"OS: {vm.get('os', 'Unknown')}")
            lbl_cpu = Gtk.Label(label=f"CPU: {vm['cpu']} Cores")
            lbl_ram = Gtk.Label(label=f"RAM: {vm['ram']}GB")
            
            box.pack_start(lbl_os, False, False, 0)
            box.pack_start(lbl_cpu, False, False, 0)
            box.pack_start(lbl_ram, False, False, 0)
            
            event_box = Gtk.EventBox()
            event_box.connect("button-press-event", self.on_vm_right_click, vm["name"])
            event_box.add(box)
            frame.add(event_box)
            self.flowbox.add(frame)
        
        self.flowbox.show_all()

    def on_vm_right_click(self, widget, event, vm_name):
        if event.button == 3:  # Right click
            menu = VMContextMenu(vm_name, self)
            menu.popup_at_pointer(event)

    def show_create_dialog(self, widget):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Create new VM",
        )
        dialog.format_secondary_text(
            "Do you want to download an OS image?"
        )
        response = dialog.run()
        dialog.destroy()
        
        if response == Gtk.ResponseType.YES:
            self.download_os()
        else:
            self.create_vm()

    def download_os(self):
        # Implement OS download logic
        pass

    def create_vm(self):
        dialog = VMConfigDialog(self)
        response = dialog.run()
        
        if response == Gtk.ResponseType.OK:
            config = {
                "name": dialog.entry_name.get_text(),
                "os": dialog.os_combo.get_active_text(),
                "cpu": dialog.entry_cpu.get_value_as_int(),
                "ram": dialog.entry_ram.get_value_as_int(),
                "disk": dialog.entry_disk.get_value_as_int(),
                "display": dialog.display_combo.get_active_text().split()[0],
                "3d_accel": dialog.accel_switch.get_active()
            }
            self.vm_configs.append(config)
            self.save_config()
            self.refresh_vm_list()
        
        dialog.destroy()

    def start_vm(self, vm_name):
        config = next(c for c in self.vm_configs if c["name"] == vm_name)
        cmd = [
            "qemu-system-x86_64",
            "-name", config["name"],
            "-m", f"{config['ram']}G",
            "-smp", str(config["cpu"]),
            "-hda", f"{config['name']}.img",
            "-display", config["display"].lower(),
            "-accel", "kvm"
        ]
        subprocess.Popen(cmd)

    def configure_vm(self, vm_name):
        config = next(c for c in self.vm_configs if c["name"] == vm_name)
        dialog = VMConfigDialog(self, vm_name, config)
        response = dialog.run()
        
        if response == Gtk.ResponseType.OK:
            # Update configuration
            pass
        
        dialog.destroy()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE) as f:
                return json.load(f)
        return []

    def save_config(self):
        if not os.path.exists(CONFIG_DIR):
            os.makedirs(CONFIG_DIR)
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.vm_configs, f)

if __name__ == "__main__":
    win = MainWindow()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
