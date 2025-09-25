"""
System Diagnostics Utilities for Billion-Air-Flow

Provides CPU, RAM, GPU, and storage diagnostic info plus a top-style dashboard.
Works on Windows and Linux (Ubuntu).
"""

import GPUtil
import math
import platform
import psutil
import re
import shutil
import subprocess


# ------------------------------
# System Model
# ------------------------------

def get_system_model():
    """Return system model string for Windows/Linux."""
    try:
        if platform.system() == "Windows":
            version = subprocess.check_output(
                [
                    "powershell", "-Command",
                    "Get-CimInstance -ClassName Win32_ComputerSystemProduct | "
                    "Select-Object Version | Format-Table -HideTableHeaders"
                ],
                text=True
            ).strip()

            if version=='':
                queryStr = "Select-Object Vendor, Name | Format-Table -HideTableHeaders"
            else:
                queryStr = "Select-Object Vendor, Version | Format-Table -HideTableHeaders"

            out = subprocess.check_output(
                [
                    "powershell", "-Command",
                    "Get-CimInstance -ClassName Win32_ComputerSystemProduct | " + queryStr
                ],
                text=True
            ).strip()
            return out
        elif platform.system() == "Linux":
            for path in [
                "/sys/devices/virtual/dmi/id/product_name",
                "/sys/devices/virtual/dmi/id/product_version",
                "/sys/devices/virtual/dmi/id/product_family"
            ]:
                try:
                    with open(path) as f:
                        out = f.read().strip()
                        if out and not out.isnumeric():
                            return out
                except FileNotFoundError:
                    continue
            return out.strip() or  platform.uname().node
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
        return f"Intel Core {family}-{model_num} ({generation})"

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
                "Select-Object Capacity, Speed | ConvertTo-Json"
            ]
            output = subprocess.check_output(cmd, text=True).strip()

            import json
            dimms = json.loads(output)
            if isinstance(dimms, dict):
                dimms = [dimms]

            sizes, speeds = [], []
            for d in dimms:
                cap = int(d.get("Capacity", 0))
                spd = d.get("Speed")
                if cap:
                    gib = cap / (1024 ** 3)  # bytes → GiB
                    sizes.append(round(gib,2))
                if spd and str(spd).isdigit():
                    speeds.append(int(spd))

            ram_info["DIMM Sizes (GB)"] = sizes
            ram_info["Advertised RAM (GB)"] = sum(sizes)
            if speeds:
                ram_info["Memory Speed (MHz)"] = sorted(set(speeds))

        except Exception as e:
            ram_info["Error"] = f"Windows query failed: {e}"

    elif system == "Linux":
        try:
            print("Attempting dmidecode for RAM info...")
            output = subprocess.check_output(
                ["dmidecode", "-t", "memory"],
                stderr=subprocess.DEVNULL, text=True
            )
            print("Successfully retrieved RAM info from dmidecode.")

            # DIMM sizes (MB → GiB)
            sizes_mb = re.findall(r"Size:\s+(\d+)\s+MB", output)
            print(f"sizes_mb: {sizes_mb}")  # Debugging line 

            sizes_gb = [round(int(s) / 1024, 2) for s in sizes_mb if s.isdigit()]
            advertised_total_gb = sum(sizes_gb) if sizes_gb else None
            print(f"advertised_total_gb: {advertised_total_gb}")  # Debugging line
    
            # Speeds
            speeds = re.findall(r"Speed:\s+(\d+)\s+MT/s", output)

            # Usable RAM from /proc/meminfo
            memtotal_kb = None
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        print(f"{line=}")  # Debugging line
                        memtotal_kb = int(line.split()[1])
                        break
            usable_gb = round(memtotal_kb / 1024**2, 2) if memtotal_kb else None

            # Reserved = advertised - usable
            reserved_mb = None
            if advertised_total_gb and usable_gb:
                reserved_mb = round(advertised_total_gb * 1024 - usable_gb * 1024, 1) * 1024
                # simpler: compute directly in MB
                advertised_mb = sum(int(s) for s in sizes_mb if s.isdigit())
                reserved_mb = advertised_mb - (memtotal_kb // 1024)

            # Populate results
            ram_info["DIMM Sizes (GB)"] = sizes_gb
            ram_info["Advertised RAM (GB)"] = advertised_total_gb
            if speeds:
                ram_info["Memory Speed (MHz)"] = sorted({int(s) for s in speeds if s.isdigit()})
            if usable_gb is not None:
                ram_info["Usable RAM (GiB)"] = usable_gb
            if reserved_mb is not None:
                ram_info["Reserved RAM (MB)"] = reserved_mb

        except Exception:
            # 🔄 Fallback: /proc/meminfo (no root required)
            try:
                with open("/proc/meminfo") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            kb = int(line.split()[1])   # value in kB
                            gib = kb / 1024**2   # kB → GiB
                            # Estimate advertised total as nearest multiple of 4 GB
                            advertised_ram = int(math.ceil(gib / 4.0)) * 4

                            ram_info["Advertised RAM (GB)"] = advertised_ram
                            ram_info["DIMM Sizes (GB)"] = [round(gib,2)]
                            break
            except Exception as e2:
                ram_info["Error"] = f"Linux query failed: {e2}"

    else:
        ram_info["Error"] = "Unsupported OS"

    return ram_info


# ------------------------------
# Storage
# ------------------------------

def get_storage_info():
    """Return list of storage devices with model, size, bus type."""
    drives = []
    if platform.system() == "Windows":
        try:
            cmd = [
                "powershell", "-Command",
                "Get-PhysicalDisk | Select-Object FriendlyName, Manufacturer, "
                "SerialNumber, Size, BusType | Format-List"
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
                    drives.append({
                        "Model": drive_info.get("FriendlyName"),
                        "Manufacturer": drive_info.get("Manufacturer"),
                        "Serial": drive_info.get("SerialNumber"),
                        "Size (GB)": round(int(size) / (1000**3), 2) if size and size.isdigit() else None,
                        "BusType": drive_info.get("BusType")
                    })
        except Exception as e:
            drives.append({"Error": str(e)})

    elif platform.system() == "Linux":
        try:
            output = subprocess.check_output(
                ["lsblk", "-d", "-o", "NAME,MODEL,VENDOR,SERIAL,SIZE,TRAN"],
                stderr=subprocess.DEVNULL, text=True
            ).strip().splitlines()
            for line in output[1:]:
                parts = line.split(None, 5)
                if len(parts) == 6:
                    name, model, vendor, serial, size, tran = parts
                    drives.append({
                        "Device": f"/dev/{name}",
                        "Model": model,
                        "Vendor": vendor,
                        "Serial": serial,
                        "Size": size,
                        "BusType": tran
                    })
        except Exception as e:
            drives.append({"Error": str(e)})

    return drives

# ------------------------------
# OS
# ------------------------------

import platform
import subprocess

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
# Diagnostics Summary
# ------------------------------

def get_system_diagnostics():
    """Collect system diagnostics into a dictionary."""
    diagnostics = {
        "System": get_system_model(),
        "CPU": get_cpu_info(),
        "RAM": get_ram_info(),
        "Storage": get_storage_info(),
        "OS": get_os_info()        
    }
    try:
        gpu_list = GPUtil.getGPUs()
        diagnostics["GPU"] = [gpu.name for gpu in gpu_list] if gpu_list else []
    except Exception:
        diagnostics["GPU"] = []
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
#    ram_total = psutil.virtual_memory().total / (1000*1024**2)
    ram_total = sysinfo["RAM"].get("Advertised RAM (GB)", [])
    ram_speed = sysinfo["RAM"].get("Memory Speed (MHz)", [])
    ram_speed_str = f"-{','.join(map(str, ram_speed))}" if ram_speed else ""
    ram_str = f"{ram_total}GB DDR{ram_speed_str}"

    # Storage
    storage_parts = []
    for d in sysinfo["Storage"]:
        model = d.get("Model", "UnknownDrive")
        size = d.get("Size (GB)") or d.get("Size")
        size_str = f"{int(round(size))}GB" if isinstance(size, (int, float)) else str(size)
        storage_parts.append(f"{model} {size_str}")
    storage_str = " | ".join(storage_parts)

    # GPU
    gpu = ",".join(sysinfo["GPU"]) if sysinfo["GPU"] else "No GPU"

    # OS
    os_info = sysinfo["OS"]

    return f"{system_model} | {cpu} | {ram_str} RAM | {storage_str} | {os_info} | {gpu}"


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