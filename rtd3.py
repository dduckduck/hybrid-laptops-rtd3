import os
import argparse


# =========================================================
# Section: Config files
# =========================================================

SYS_FILES = {
    "chassis": "/sys/class/dmi/id/chassis_type",
    "acpi": "/sys/firmware/acpi/tables/DSDT",  # requires root access
    "kernel": "/proc/version",
    "s3": "/sys/power/mem_sleep"
}

DGPU_FILES = {
    "gpus": "/proc/driver/nvidia/gpus/",
    "rtd3_status": "/proc/driver/nvidia/gpus/{}/power",
    "power_state": "/sys/bus/pci/devices/{}/power_state",
    "runtime_status": "/sys/bus/pci/devices/{}/power/runtime_status"
}


BAT_FILES = {
    "power_supply": "/sys/class/power_supply/",
    "power_now": "/sys/class/power_supply/{}/power_now",
}


NVIDIA_FILES = {
    "udev": {  # Requires root access
        "path": [
            "/lib/udev/rules.d/80-nvidia-pm.rules",
            "/etc/udev/rules.d/80-nvidia-pm.rules"
        ],
        "value": """# Enable runtime PM for NVIDIA VGA/3D controller devices on driver bind
ACTION=="bind", SUBSYSTEM=="pci", ATTR{vendor}=="0x10de", ATTR{class}=="0x030000", TEST=="power/control", ATTR{power/control}="auto"
ACTION=="bind", SUBSYSTEM=="pci", ATTR{vendor}=="0x10de", ATTR{class}=="0x030200", TEST=="power/control", ATTR{power/control}="auto"

# Disable runtime PM for NVIDIA VGA/3D controller devices on driver unbind
ACTION=="unbind", SUBSYSTEM=="pci", ATTR{vendor}=="0x10de", ATTR{class}=="0x030000", TEST=="power/control", ATTR{power/control}="on"
ACTION=="unbind", SUBSYSTEM=="pci", ATTR{vendor}=="0x10de", ATTR{class}=="0x030200", TEST=="power/control", ATTR{power/control}="on"
"""},
    "modprobe": {  # Requires root access
        "path": [
            "/etc/modprobe.d/nvidia-pm.conf",
            "/etc/modprobe.d/nvidia.conf"
        ],
        "value_template": """options nvidia NVreg_DynamicPowerManagement=0x0{}
options nvidia NVreg_EnableGpuFirmware={}
"""
    }
}


# =========================================================
# Section: Basic operations
# =========================================================


def _read_file(path: str, mode: str = 'r') -> str:
    data = ""
    try:
        with open(path, mode) as f:
            if mode == "rb":
                data = f.read().decode(errors="ignore")
            else:
                data = f.read()
    except Exception as e:
        print(f"Could not read {path} {str(e)}")
    return data


def _list_dir(path: str) -> list:
    output = []
    try:
        output = os.listdir(path)
    except Exception as e:
        print(f"Could not list {path} {str(e)}")
    return output


def _find_file(paths: list) -> str:
    output = ""
    try:
        for path in paths:
            if os.path.exists(path):
                output = path
                break
    except Exception as e:
        print(f"Could not find path :{str(e)}")
    return output


def _extract_data(value: str, data: str) -> str:
    output = ""
    match value:
        case "kernel":
            temp = data.strip().split()
            output = temp[2] if len(temp) >= 3 else "Unknown"
        case "chassis":
            output = data.strip()
        case "acpi":
            output = ", ".join(tag for tag in ["_PR0", "_PR3"] if tag in data)
        case "s3":
            output = "deep" if "deep" in data else "None"
        case "rtd3_status":
            temp = data.splitlines()[0]
            if "Runtime D3 status" in temp:
                output = temp.split(':', 1)[1].strip()
        case "power_state":
            output = data.strip()
        case "runtime_status":
            output = data.strip()
    return output


def _validate(value: str, data: str) -> bool:
    output = False
    match value:
        case "kernel":
            nums = data.split('.')
            first, second = -1, -1
            if nums and len(nums) >= 2:
                first, second = (map(int, nums[:2]))
            output = (first, second) >= (4, 18)
        case "chassis":
            output = ("10" == data)
        case "acpi":
            output = ("_PR0" in data and "_PR3" in data)
        case "s3":
            output = "deep" in data
        case "udev":
            output = NVIDIA_FILES["udev"]["value"] in data
    return output


def _power_watts(value: str) -> int:
    power_draw = -1
    try:
        power_draw = int(value)
    except Exception as e:
        print(f"Clould not obtain power draw {str(e)}")
    return power_draw*(10**-6)


def _create_file(path: str, data: str):
    print(f"Creating: {path}")
    try:
        if os.path.exists(path):
            print(f"{path} already exists. Creating backup...")
            backup_path = f"{path}.bak"
            os.rename(path, backup_path)
            print(f"Backup created at {backup_path}")

        if not os.path.exists(os.path.dirname(path)):
            print(f"Creating new file {path}")
            os.makedirs(os.path.dirname(path))

        with open(path, 'w') as f:
            print(f"Writing data to : {path}")
            f.write(data)
        print(f"Successfully installed {path}")
    except Exception as e:
        print(f"Could not finish the installation {str(e)}")

# =========================================================
# Section: Utilities
# =========================================================


def _print_table(headers: list[str], rows: list[list[str]], margin: int = 2, name="Table") -> None:
    col_width = max([len(str(val)) for val in headers] + [len(str(val))
                    for row in rows for val in row]) + margin
    table_width = col_width * len(headers)
    print(name.center(table_width, '='))
    header = "".join(f"{header:<{col_width}}" for header in headers)
    print(header)
    print('-' * table_width)
    for row in rows:
        row_str = "".join(f"{val:<{col_width}}" for val in row)
        print(row_str)
    print('=' * table_width)


# =========================================================
# Section: Commands
# =========================================================


def verify() -> dict:
    headers = ["Check", "Value", "Supported"]
    rows = []
    for key, value in SYS_FILES.items():
        mode = 'rb' if key == "acpi" else 'r'
        raw_file = _read_file(value, mode)
        data = _extract_data(key, raw_file)
        supported = _validate(key, data)
        row = [key, data, str(supported)]
        rows.append(row)
    _print_table(headers, rows, name="Requirements")


def state() -> dict:
    slots = _list_dir(DGPU_FILES["gpus"])
    for slot in slots:
        headers = ["key", "value"]
        rows = []
        for key, value in [(k, v) for (k, v) in DGPU_FILES.items() if k != "gpus"]:
            raw_file = _read_file(value.format(slot))
            data = _extract_data(key, raw_file)
            row = [key, data]
            rows.append(row)
        rows.append(['-'*5, '-'*5])
    batts = [bat for bat in _list_dir(
        BAT_FILES["power_supply"]) if "BAT" in bat]
    for batt in batts:
        path = BAT_FILES["power_now"].format(batt)
        raw_value = _read_file(path)
        power_now = _power_watts(raw_value)
        row = [batt, f"{power_now:.2f} W"]
        rows.append(row)
    rows.append(['-'*5, '-'*5])
    for k in NVIDIA_FILES.keys():
        valid_path = _find_file(NVIDIA_FILES[k]["path"])
        row = [k, f"{'Found' if valid_path else 'Not found'}"]
        rows.append(row)
    _print_table(headers, rows, name="Power supply")


def install(power_mode: int, enable_firmware: int) -> None:
    print("Starting installation")
    udev_path = _find_file(NVIDIA_FILES["udev"]["path"])
    udev_path = udev_path if udev_path else NVIDIA_FILES["udev"]["path"][0]
    udev_data = NVIDIA_FILES["udev"]["value"]
    _create_file(udev_path, udev_data)

    modprobe_path = _find_file(NVIDIA_FILES["modprobe"]["path"])
    modprobe_path = modprobe_path if modprobe_path else NVIDIA_FILES["modprobe"]["path"][0]
    modprobe_data = NVIDIA_FILES["modprobe"]["value_template"].format(
        power_mode, enable_firmware)
    _create_file(modprobe_path, modprobe_data)


# =========================================================
# Section: Main and arguments
# =========================================================


def setup_args() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="RTD3 Tool: A utility for managing and diagnosing NVIDIA GPU power management on hybrid laptops.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_info = subparsers.add_parser("info", help="Shows info")
    parser_info.add_argument("-v", "--verify", action="store_true",
                             help="Verifies system requirements as specified in nvidia docs.")
    parser_info.add_argument("-s", "--state", action="store_true",
                             help="Show the current status of the dGPU, battery and indicate if the udev and modprobe files are present.\
                             If more than one dgpu or battery available, individual information for each device will be shown")

    parser_install = subparsers.add_parser(
        "install", help="install udev and modprobe files. if these files already exist, a backup will be created.\
                        (If a backup exists, the installation wont be completed.")
    parser_install.add_argument(
        "-p", "--powermode", type=int, choices=[0, 1, 2], default=2,
        help=(
            "Configure NVIDIA dynamic power management (NVreg_DynamicPowerManagement): \
            0 - disables D3 power management, 1 - enables coarse-grained power control, 2 - enable fine-grained power control.\
            Default value is 2. \
            For more information: https://download.nvidia.com/XFree86/Linux-x86_64/565.77/README/dynamicpowermanagement.html"
        )
    )

    parser_install.add_argument("-e", "--enablefirmware", type=int, choices=[0, 1], default=0,
                                help="Enables (1) or disables (0) GpuFirmware. Only works on the closed source driver. Default 0.")
    return parser


def main(parser: argparse.ArgumentParser) -> None:
    args = parser.parse_args()
    match(args.command):
        case "info":
            if args.verify:
                verify()
            elif args.state:
                state()
        case "install":
            install(args.powermode, args.enablefirmware)
        case _:
            parser.print_help()


if __name__ == "__main__":
    parser = setup_args()
    main(parser)
