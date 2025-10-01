"""
System Diagnostics Utilities

Provides CPU, RAM, GPU, and storage diagnostic info plus a top-style dashboard.
Works on Windows, Linux (Ubuntu), and macOS.
"""

import ast
import json
import math
import platform
import psutil
import re
import shutil
import subprocess

import pystackinfo

checkGPU = False
try:
    import GPUtil
    checkGPU = True
except ImportError:
    checkGPU = False

# ------------------------------
# System Model
# ------------------------------

def get_system_model():
    """Return system model string for Windows/Linux/macOS."""
    try:
        system = platform.system()

        if system == "Windows":
            version = subprocess.check_output(
                [
                    "powershell", "-Command",
                    "Get-CimInstance -ClassName Win32_ComputerSystemProduct | "
                    "Select-Object Version | Format-Table -HideTableHeaders"
                ],
                text=True
            ).strip()

            vendor = subprocess.check_output(
                [
                    "powershell", "-Command",
                    "Get-CimInstance -ClassName Win32_ComputerSystemProduct | "
                    "Select-Object Vendor | Format-Table -HideTableHeaders"
                ],
                text=True
            ).strip()

            # Remove trailing punctuation (.,)
            vendor = re.sub(r"[.,\s]+$", "", vendor)

            # Remove common company suffixes
            vendor = re.sub(r"\b(inc|inc\.|ltd|ltd\.|corp|co\.?)\b$", "", vendor, flags=re.IGNORECASE)

            # Remove any leftover trailing punctuation/whitespace again
            vendor = re.sub(r"[.,\s]+$", "", vendor)

            if version == '':
                queryStr = "Select-Object Name | Format-Table -HideTableHeaders"
            else:
                queryStr = "Select-Object Version | Format-Table -HideTableHeaders"

            out = subprocess.check_output(
                [
                    "powershell", "-Command",
                    "Get-CimInstance -ClassName Win32_ComputerSystemProduct | " + queryStr
                ],
                text=True
            ).strip()

            return vendor + ' ' + out

        elif system == "Linux":
            vendor, model = None, None
            try:
                with open("/sys/devices/virtual/dmi/id/sys_vendor") as f:
                    vendor = f.read().strip()
            except FileNotFoundError:
                pass
            try:
                with open("/sys/devices/virtual/dmi/id/product_name") as f:
                    model = f.read().strip()
            except FileNotFoundError:
                pass
            
            if vendor:
                vendor = vendor.strip()

                # Remove trailing punctuation (.,)
                vendor = re.sub(r"[.,\s]+$", "", vendor)

                # Remove common company suffixes
                vendor = re.sub(r"\b(inc|inc\.|ltd|ltd\.|corp|co\.?)\b$", "", vendor, flags=re.IGNORECASE)

                # Remove any leftover trailing punctuation/whitespace again
                vendor = re.sub(r"[.,\s]+$", "", vendor)

            if vendor and model:
                return f"{vendor} {model}"
            elif model:
                return model
            elif vendor:
                return vendor
            else:
                return platform.uname().node

        elif system == "Darwin":  # macOS
            try:
                output = subprocess.check_output(
                    ["system_profiler", "SPHardwareDataType"],
                    text=True
                )
                model_name, model_id = None, None
                for line in output.splitlines():
                    if "Model Name:" in line:
                        model_name = line.split(":", 1)[1].strip()
                    elif "Model Identifier:" in line:
                        model_id = line.split(":", 1)[1].strip()
                if model_name and model_id:
                    return f"Apple {model_name} ({model_id})"
                elif model_name:
                    return f"Apple {model_name}"
                else:
                    return "Apple Mac"
            except Exception:
                return platform.uname().node

        else:
            return platform.uname().node

    except Exception:
        return "Unknown System"

# ------------------------------
# CPU
# ------------------------------

def get_cpu_info():
    """Return CPU info dict (raw name, friendly name, cores, threads, speed)."""
    system = platform.system()
    raw_name = ""

    if system == "Windows":
        # Try PowerShell
        try:
            cmd = ["powershell", "-Command", "(Get-CimInstance Win32_Processor).Name"]
            raw_name = subprocess.check_output(cmd, text=True).strip()
        except Exception:
            pass

        # Fallback: WMIC
        if not raw_name:
            try:
                output = subprocess.check_output(
                    ["wmic", "cpu", "get", "Name"], text=True
                ).strip().splitlines()
                if len(output) > 1:
                    raw_name = output[1].strip()
            except Exception:
                pass

    elif system == "Linux":
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "model name" in line:
                        raw_name = line.split(":")[1].strip()
                        break
        except Exception:
            pass

    if not raw_name:
        raw_name = platform.processor()

    friendly_name = make_friendly_cpu_name(raw_name)
    cpu_count = psutil.cpu_count(logical=True)
    cpu_physical = psutil.cpu_count(logical=False)

    freq = psutil.cpu_freq()
    cpu_speed = {
        "Min (MHz)": round(freq.min, 2),
        "Max (MHz)": round(freq.max, 2),
        "Current (MHz)": round(freq.current, 2)
    } if freq else "Unavailable"

    return {
        "CPU Name (Raw)": raw_name,
        "CPU Name (Friendly)": friendly_name,
        "Cores (Physical)": cpu_physical,
        "Threads (Logical)": cpu_count,
        "Clock Speed": cpu_speed
    }


def make_friendly_cpu_name(raw_name):
    """Simplify CPU name and detect Intel generation if possible."""
    if not raw_name:
        return "Unknown CPU"

    name = re.sub(r"\(R\)|\(TM\)|CPU|@.*GHz", "", raw_name, flags=re.IGNORECASE)
    name = re.sub(r"\s+", " ", name).strip()

    # Intel Core parsing
    match = re.search(r"(i3|i5|i7|i9)-(\d{3,5})", name)
    if match:
        family, model_num = match.groups()
        model_num = int(model_num)
        if model_num < 1000:
            generation = "1st Gen (very old)"
        elif model_num < 10000:  # e.g. 8700 -> 8th gen
            generation = f"{str(model_num)[0]}th Gen"
        else:  # e.g. 10700 -> 10th gen
            generation = f"{str(model_num)[:2]}th Gen"
        return f"Intel Core {family}-{model_num}"  # optionally: + f" ({generation})"

    # AMD Ryzen
    if "Ryzen" in name:
        return name

    return name


# ------------------------------
# RAM
# ------------------------------

def get_ram_info():
    """
    Return advertised RAM total (GB), individual DIMM sizes, and memory speeds.
    Uses PowerShell on Windows and dmidecode on Linux.
    Reports sizes as whole-number GiB (to match DIMM labels).
    """
    system = platform.system()
    ram_info = {
        "Advertised RAM (GB)": None,
        "DIMM Sizes (GB)": [],
        "Memory Speed (MHz)": []
    }

    if system == "Windows":
        try:
            cmd = [
                "powershell", "-Command",
                "$ProgressPreference = 'SilentlyContinue'; "
                "Get-CimInstance Win32_PhysicalMemory | "
                "Select-Object Capacity, Speed, SMBIOSMemoryType | ConvertTo-Json"
            ]
            output = subprocess.check_output(cmd, text=True).strip()

            import json
            dimms = json.loads(output)
            if isinstance(dimms, dict):
                dimms = [dimms]

            sizes, speeds, types = [], [], []
            type_map = {
                20: "DDR",
                21: "DDR2",
                24: "DDR3",
                26: "DDR4",
                27: "LPDDR",
                28: "LPDDR2",
                29: "LPDDR3",
                30: "LPDDR4",
            }

            for d in dimms:
                cap = int(d.get("Capacity", 0) or 0)
                spd = d.get("Speed")
                tcode = d.get("SMBIOSMemoryType")

                if cap:
                    gib = cap / (1024 ** 3)  # bytes → GiB
                    val = round(gib, 2)
                    # if val is an integer, make it int not float
                    if val.is_integer():
                        val = int(val)
                    sizes.append(val)

                if spd and str(spd).isdigit():
                    speeds.append(int(spd))
                if tcode and str(tcode).isdigit():
                    tcode = int(tcode)
                    if tcode in type_map:
                        types.append(type_map[tcode])

            total = sum(sizes) if sizes else None
            if total is not None and isinstance(total, float) and total.is_integer():
                total = int(total)

            ram_info["DIMM Sizes (GB)"] = sizes
            ram_info["Advertised RAM (GB)"] = total
            if speeds:
                ram_info["Memory Speed (MHz)"] = sorted(set(speeds))
            if types:
                ram_info["Memory Type"] = types[0] if all(x == types[0] for x in types) else types

        except Exception as e:
            ram_info["Error"] = f"Windows query failed: {e}"

    elif system == "Linux":
        ram_info["IsLikelyDDR"] = None  # default        
        sizes, types, speeds = [], [], []

        # ✅ Always get usable/total memory from /proc/meminfo
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])  # value in kB
                        gib = kb / 1024**2        # kB → GiB
                        advertised_ram = int(math.ceil(gib / 4.0)) * 4  # round up to nearest 4 GB
                        ram_info["Advertised RAM (GB)"] = advertised_ram
                        ram_info["DIMM Sizes (GB)"] = [round(gib, 2)]
                        ram_info["Usable RAM (GiB)"] = round(gib, 2)
                        break
        except Exception as e:
            ram_info["Error"] = f"/proc/meminfo query failed: {e}"

        # ✅ Try decode-dimms for type + speed (optional)
        try:
            output = subprocess.check_output(
                ["decode-dimms"], text=True, stderr=subprocess.DEVNULL
            )

            raw_types = re.findall(r"(DDR\d(?:-\d+)?)", output)
            raw_types = list(set(raw_types))  # deduplicate
            ram_info["IsLikelyDDR"] = True

            if raw_types:
                base_type = None
                max_speed = None
                for t in raw_types:
                    if "-" in t:
                        family, mhz = t.split("-")
                        mhz = int(mhz)
                        if max_speed is None or mhz > max_speed:
                            max_speed = mhz
                        base_type = family
                    else:
                        base_type = t
                if base_type:
                    ram_info["Memory Type"] = base_type
                if max_speed:
                    ram_info["Memory Speed (MHz)"] = [max_speed]

        except Exception:
            # CPU fallback if still unknown
            if ram_info.get("IsLikelyDDR") is None:
                try:
                    with open("/proc/cpuinfo") as f:
                        cpuinfo = f.read()
                    if re.search(r"(Core|Xeon|Pentium\s4|Celeron\sD|Athlon\s64|Opteron|Turion|Phenom|i[3579]|Ryzen)", cpuinfo, re.I):
                        ram_info["IsLikelyDDR"] = True
                    else:
                        ram_info["IsLikelyDDR"] = False
                except Exception:
                    ram_info["IsLikelyDDR"] = False

            if ram_info["IsLikelyDDR"]: 
                ram_info["Memory Type"] = "DDR"
            else:
                ram_info["Memory Type"] = ""

    elif system == "Darwin":  # macOS
        try:
            # Total RAM
            total_bytes = int(subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"], text=True).strip()
            )
            ram_info["Advertised RAM (GB)"] = round(total_bytes / (1024**3))

            sizes, speeds, types = [], [], []

            # Always parse plain text (since XML is unreliable on older Macs)
            text_out = subprocess.check_output(
                ["system_profiler", "SPMemoryDataType"],
                text=True, errors="ignore"
            )

            # Sizes (lines like "Size: 2 GB")
            size_matches = re.findall(r"Size:\s+(\d+)\s+GB", text_out)
            if size_matches:
                sizes = [int(s) for s in size_matches if s.isdigit()]

            # Types: "Type: DDR3" or "Type: Empty"
            type_matches = re.findall(r"Type:\s*([A-Za-z0-9]+)", text_out, flags=re.IGNORECASE)
            if type_matches:
                # Remove "Empty"
                cleaned_types = [t for t in type_matches if t.lower() != "empty"]

                if cleaned_types:
                    # Collapse to single string if all the same
                    if all(x == cleaned_types[0] for x in cleaned_types):
                        ram_info["Memory Type"] = cleaned_types[0]
                    else:
                        ram_info["Memory Type"] = cleaned_types

            if types:
                ram_info["Memory Type"] = types[0] if len(types) == 1 else types

            # Speeds (lines like "Speed: 1333 MHz")
            max_speeds = re.findall(r"Maximum Speed:\s+(\d+)\s+MT/s", output)
            cfg_speeds = re.findall(r"Speed:\s+(\d+)\s+MT/s", output)

            speeds = []
            if max_speeds:
                speeds = [int(s) for s in max_speeds if s.isdigit()]
            elif cfg_speeds:
                speeds = [int(s) for s in cfg_speeds if s.isdigit()]

            # Populate results
            if sizes:
                ram_info["DIMM Sizes (GB)"] = sizes
            if speeds:
                ram_info["Memory Speed (MHz)"] = sorted(set(speeds))
            if types:
                ram_info["Memory Type"] = types[0] if len(types) == 1 else types

            # Slot count
            slot_matches = re.findall(r"BANK \d+/DIMM\d+:", text_out)
            ram_info["Slots Used"] = len(sizes)
            ram_info["Slots Total"] = len(slot_matches)

        except Exception as e:
            ram_info["Error"] = f"macOS query failed: {e}"



    else:
        ram_info["Error"] = "Unsupported OS"

    return ram_info


# ------------------------------
# Storage
# ------------------------------

def bytes_to_str(size_bytes):
    """Convert size in bytes to a human-readable string in GB."""
    if size_bytes is None:
        return "Unknown"
    size_tb = round(size_bytes / (1000**4))
    size_gb = round(size_bytes / (1000**3))
    size_mb = round(size_bytes / (1000**2))
    size_kb = round(size_bytes / 1000)
    return f"{size_tb}TB" if size_gb >= 1000 else f"{size_gb}GB" if size_mb >= 1000 else f"{size_mb}MB" if size_kb >= 1000 else f"{size_kb}KB" if size_kb >= 1  else f"{size_bytes}B"

def is_linux_storage_removable(dev_name: str) -> bool:
    """
    Returns True if the given device is removable, False otherwise.
    dev_name is like 'sda', 'nvme0n1', etc.
    """
    removable_path = f"/sys/block/{dev_name}/removable"
    try:
        with open(removable_path) as f:
            return f.read().strip() == "1"
    except FileNotFoundError:
        return False
    
def get_storage_info():
    """Return list of storage devices with model, size, bus type, and media type (HDD/SSD/USB/NVMe/MMC)."""
    drives = []
    system = platform.system()

    if system == "Windows":
        try:
            cmd = [
                "powershell", "-Command",
                "Get-PhysicalDisk | Select-Object FriendlyName, Manufacturer, "
                "SerialNumber, Size, BusType, MediaType | Format-List"
            ]
            output = subprocess.check_output(cmd, text=True)
            blocks = re.split(r"\n\s*\n", output.strip())
            for block in blocks:
                drive_info = {}
                for line in block.splitlines():
                    if ":" in line:
                        key, val = line.split(":", 1)
                        drive_info[key.strip()] = val.strip()
                if drive_info:
                    size = drive_info.get("Size")
                    bus = drive_info.get("BusType", "").upper()
                    media = drive_info.get("MediaType", "").upper()

                    # Decide MediaType
                    if bus == "USB":
                        media_type = "USB"
                    elif bus in ("NVME", "SATA"):
                        if media == "SSD":
                            media_type = "SSD"
                        elif media == "HDD":
                            media_type = "HDD"
                        else:
                            media_type = bus  # fallback
                    else:
                        media_type = bus or "Unknown"

                    drives.append({
                        "Model": drive_info.get("FriendlyName"),
                        "Manufacturer": drive_info.get("Manufacturer"),
                        "Serial": drive_info.get("SerialNumber"),
                        "Size": bytes_to_str(int(size)) if size and size.isdigit() else size if size else None,
                        "BusType": bus,
                        "MediaType": media_type
                    })
        except Exception as e:
            drives.append({"Error": str(e)})

    elif system == "Linux":
        output = subprocess.check_output(
            ["lsblk", "-J", "-bd", "-o", "NAME,MODEL,VENDOR,SERIAL,SIZE,TRAN"],
            stderr=subprocess.DEVNULL, text=True
        )
        output = json.loads(output)
        blockdevices = output['blockdevices']

        storagedevices = []
        for dev in blockdevices:
            name = dev.get("name")
            if not name.startswith("loop") and not name.startswith("ram"):
                storagedevices.append(dev)

        for dev in storagedevices:
            try:
                name = dev.get("name")
                model = dev.get("model", "")
                vendor = dev.get("vendor", "")
                serial = dev.get("serial", "")
                size = dev.get("size", "")
                tran = dev.get("tran", "").strip().upper() if dev.get("tran") else "UNKNOWN"

                name = name.strip() if isinstance(name, str) else name
                model = model.strip() if isinstance(model, str) else model
                vendor = vendor.strip() if isinstance(vendor, str) else vendor
                serial = serial.strip() if isinstance(serial, str) else serial
                size = size.strip() if isinstance(size, str) else size

                dev_path = f"/dev/{name}"
                bus = tran.upper()
                bus = bus.split(' ')[-1]

                # Rotational flag for HDD/SSD
                rota_path = f"/sys/block/{name}/queue/rotational"
                media_type = bus.split(' ')[-1]

                with open(rota_path) as f:
                    rota = f.read().strip()
                    if bus in ("SATA", "NVME"):
                        media_type = "SSD" if rota == "0" else "HDD"

                drives.append({
                    "Device": dev_path,
                    "Model": model,
                    "Vendor": vendor,
                    "Serial": serial,
                    "Size": size if size and isinstance(size, str) else bytes_to_str(int(size)) if size else None,
                    "BusType": bus,
                    "MediaType": media_type
                })
            except Exception as e:
                drives.append({"Error": str(e)})


    elif system == "Darwin":  # macOS
        try:
            disk_list = subprocess.check_output(
                ["diskutil", "list"], text=True
            ).strip().splitlines()

            for line in disk_list:
                m = re.match(r"^\s*(\S+)\s+\(.*\):", line)
                if m:
                    dev = m.group(1)  # e.g. disk0
                    try:
                        info = subprocess.check_output(
                            ["diskutil", "info", dev], text=True
                        )
                        drive = {"Device": f"/dev/{dev}"}
                        media_type, size = None, None
                        for l in info.splitlines():
                            if "Device / Media Name:" in l:
                                drive["Model"] = l.split(":", 1)[1].strip()
                            elif "Disk Size:" in l and "(" in l:
                                size = l.split("(")[0].split(":")[1].strip()
                            elif "Solid State:" in l:
                                if "Yes" in l:
                                    media_type = "SSD"
                                elif "No" in l:
                                    media_type = "HDD"
                            elif "Protocol:" in l:
                                proto = l.split(":", 1)[1].strip().upper()
                                if media_type is None:
                                    media_type = proto  # e.g. USB

                        print(f"{size=}")
#                        print(re.search(r'"([^"]+)"', size).group(1))
#                        print(ast.literal_eval(size)[0])
#
#                        size = re.search(r'"([^"]+)"', size).group(1) # ast.literal_eval(size)[0]
                        drive["Size"] = size
                        drive["MediaType"] = media_type or "Unknown"


                        print(f"{drive=}")


                        drives.append(drive)
                    except Exception:
                        continue
        except Exception as e:
            drives.append({"Error": str(e)})

    return drives


# ------------------------------
# OS
# ------------------------------

def get_MacOS_version() -> str:
    """
    Return a string describing the macOS version and Darwin kernel version.
    Example: 'macOS 14.3.1 (Darwin 23.4.0)'
    """
    try:
        product = subprocess.check_output(
            ["sw_vers", "-productName"], text=True
        ).strip()
        version = subprocess.check_output(
            ["sw_vers", "-productVersion"], text=True
        ).strip()
        kernel = platform.release()  # Darwin kernel version, e.g. '23.4.0'
        return f"{product} {version} (Darwin {kernel})"
    except Exception as e:
        return f"macOS (Darwin {platform.release()}) - version lookup failed: {e}"

def get_linux_distro():
    try:
        with open("/etc/os-release") as f:
            data = {}
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    data[k] = v.strip('"')
        return f"{data.get('NAME')} {data.get('VERSION')}"
    except Exception:
        return f"Linux {platform.release()}"
    
def get_os_info():
    system = platform.system()
    if system == "Linux":
        return get_linux_distro()
    elif system == "Darwin":
        return get_MacOS_version()
    elif system == "Windows":
        try:
            cmd = ["powershell", "-Command", "(Get-CimInstance Win32_OperatingSystem).Caption"]
            return subprocess.check_output(cmd, text=True).strip()
        except Exception:
            return f"Windows {platform.release()}"
    else:
        return f"{system} {platform.release()}"

# ------------------------------
# GPU
# ------------------------------

def get_gpu_info():
    """Return GPU info dict (raw name, friendly name, memory, driver version)."""
    gpus = []
    try:
        gpu_list = GPUtil.getGPUs()
        for gpu in gpu_list:
            gpu_memory = gpu.memoryTotal if gpu.memoryTotal else None
            if gpu_memory and isinstance(gpu_memory, float) and gpu_memory.is_integer():
                gpu_memory = int(gpu_memory)
                if math.log(gpu_memory,2) >= 10 and math.log(gpu_memory,2).is_integer():    
                    gpu_memory_str = f"{gpu_memory//1024}GB"
                else:
                    gpu_memory_str = f"{gpu_memory}MB"
            else:
                gpu_memory_str = ""

            gpu_str = gpu.name + (f" {gpu_memory_str}" if gpu_memory_str else "")

            gpus.append({
                "GPU": gpu_str,
                "GPU Name": gpu.name,
                "GPU Memory": gpu_memory_str,
                "Driver Version": gpu.driver  
            })
    except Exception as e:
        gpus.append({"Error": str(e)})
    return gpus


# ------------------------------
# Diagnostics Summary
# ------------------------------

def get_system_diagnostics():
    """Collect system diagnostics into a dictionary."""
    diagnostics = {
        "System": get_system_model(),
        "CPU": get_cpu_info(),
        "RAM": get_ram_info(),
        "Storage": get_storage_info(),
        "OS": get_os_info(),
        "GPU": get_gpu_info() if checkGPU else []           
    }
    return diagnostics


def system_summary():
    """Return a one-line system summary string."""
    sysinfo = get_system_diagnostics()

    # System
    system_model = sysinfo["System"]

    # CPU
    cpu = sysinfo["CPU"].get("CPU Name (Friendly)") or sysinfo["CPU"].get("CPU Name (Raw)")
    cores = sysinfo["CPU"].get("Cores (Physical)", "?")
    threads = sysinfo["CPU"].get("Threads (Logical)", "?")

    if cpu.endswith(")"):
        # Insert before closing parenthesis
        cpu = re.sub(r"\)$", f", {cores}c/{threads}t)", cpu)
    else:
        cpu += f" ({cores}c/{threads}t)"

    # RAM
    ram_total = sysinfo["RAM"].get("Advertised RAM (GB)")
    ram_type = sysinfo["RAM"].get("Memory Type", "")
    ram_speed = sysinfo["RAM"].get("Memory Speed (MHz)", [])

    # Format speed nicely (e.g. "1333" → "1333")
    ram_speed_str = f"-{','.join(map(str, ram_speed))}" if ram_speed else ""

    # Final string, e.g. "4GB DDR3-1333 RAM"
    ram_str = f"{ram_total}GB {ram_type}{ram_speed_str} RAM"
    
    # Storage
    storage_parts = []
    print("STORAGE:", sysinfo["Storage"])
    for d in sysinfo["Storage"]:
        vendor = d.get("Vendor", "")
        if vendor:
            vendor = vendor.strip()
            vendor = "" if vendor.upper() =="SATA" or vendor.upper() =="ATA" or vendor.upper() =="NVME" else vendor
        else:
            vendor = ""  
        model = d.get("Model", "UnknownDrive")
        size = d.get("Size")
        media_type = d.get("MediaType", "")
        storage_parts.append(f"{vendor} {model} {size} {media_type}".strip())
    storage_str = " | ".join(storage_parts)

    # OS
    os_info = sysinfo["OS"]

    # GPU
    gpu = ""
    if checkGPU:
        gpu_info = sysinfo["GPU"]
        if gpu_info and isinstance(gpu_info, list) and "Error" not in gpu_info[0]:
            gpu = ",".join([f"{info['GPU']} " for info in gpu_info]).strip()

    retStr = f"{system_model} | {cpu} CPU | {ram_str} | {storage_str} | {os_info} OS"
    if gpu:
        retStr += f" | {gpu} GPU"

    py_stack = pystackinfo.pystack_summary()
    retStr += f" | {py_stack}"

    return retStr

# ------------------------------
# Dashboard
# ------------------------------

def make_bar(fraction, width=20):
    """Make a simple [#####.....] bar."""
    filled = int(round(width * fraction))
    return "[" + "#" * filled + "." * (width - filled) + "]"


def snapshot_dashboard():
    """Return a one-time CPU+RAM usage dashboard string."""
    cols = shutil.get_terminal_size((80, 20)).columns
    bar_width = max(10, min(40, cols // 4))

    lines = ["CPU Usage:"]
    for i, pct in enumerate(psutil.cpu_percent(percpu=True)):
        lines.append(f" Core {i:2}: {make_bar(pct/100, bar_width)} {pct:5.1f}%")

    vm = psutil.virtual_memory()
    ram_fraction = vm.used / vm.total
    used_gb = vm.used / (1024**3)
    total_gb = vm.total / (1024**3)
    lines.append("RAM Usage:")
    lines.append(
        f" {make_bar(ram_fraction, bar_width)} {ram_fraction*100:5.1f}% "
        f"({round(used_gb,1)}GB / {round(total_gb):d}GB)"
    )

    return "\n".join(lines)


# ------------------------------
# Main
# ------------------------------

if __name__ == "__main__":
    print(system_summary())
