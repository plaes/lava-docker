#!/usr/bin/env python
#
from __future__ import print_function
import os, sys, time
import subprocess
import argparse
import yaml
import string
import socket
import shutil

# Defaults
boards_yaml = "boards.yaml"
tokens_yaml = "tokens.yaml"
baud_default = 115200
    
template_conmux = string.Template("""#
# auto-generated by lavalab-gen.py for ${board}
#
listener ${board}
application console '${board} console' 'exec sg dialout "cu-loop /dev/${board} ${baud}"'
""")

#no comment it is volontary
template_device = string.Template("""{% extends '${devicetype}.jinja2' %}
""")

template_device_conmux = string.Template("""
{% set connection_command = 'conmux-console ${board}' %}
""")
template_device_connection_command = string.Template("""#
{% set connection_command = '${connection_command}' %}
""")
template_device_pdu_generic = string.Template("""
{% set hard_reset_command = '${hard_reset_command}' %}
{% set power_off_command = '${power_off_command}' %}
{% set power_on_command = '${power_on_command}' %}
""")

template_udev_serial = string.Template("""#
SUBSYSTEM=="tty", ATTRS{idVendor}=="${idvendor}", ATTRS{idProduct}=="${idproduct}", ATTRS{serial}=="${serial}", MODE="0664", OWNER="uucp", SYMLINK+="${board}"
""")
template_udev_devpath = string.Template("""#
SUBSYSTEM=="tty", ATTRS{idVendor}=="${idvendor}", ATTRS{idProduct}=="${idproduct}", ATTRS{devpath}=="${devpath}", MODE="0664", OWNER="uucp", SYMLINK+="${board}"
""")

def main(args):
    fp = open(boards_yaml, "r")
    labs = yaml.load(fp)
    fp.close()
    tdc = open("docker-compose.template", "r")
    dockcomp = yaml.load(tdc)
    tdc.close()

    # The slaves directory must exists
    if not os.path.isdir("lava-master/slaves/"):
        os.mkdir("lava-master/slaves/")
        fp = open("lava-master/slaves/.empty", "w")
        fp.close()
    if not os.path.isdir("lava-slave/conmux/"):
        os.mkdir("lava-slave/conmux/")
        fp = open("lava-slave/conmux/.empty", "w")
        fp.close()

    for lab_name in labs:
        udev_line =""
        lab = labs[lab_name]
        use_kvm = False
        if "host_has_cpuflag_kvm" in lab:
            use_kvm = lab["host_has_cpuflag_kvm"]
        if use_kvm:
            if "devices" in dockcomp["services"][lab_name]:
                dc_devices = dockcomp["services"][lab_name]["devices"]
            else:
                dockcomp["services"][lab_name]["devices"] = []
                dc_devices = dockcomp["services"][lab_name]["devices"]
            dc_devices.append("/dev/kvm:/dev/kvm")
        for board_name in lab["boardlist"]:
            b = lab["boardlist"][board_name]
            if b.get("disabled", None):
                continue

            devicetype = b["type"]
            device_line = template_device.substitute(devicetype=devicetype)
            if "pdu_generic" in b:
                hard_reset_command = b["pdu_generic"]["hard_reset_command"]
                power_off_command = b["pdu_generic"]["power_off_command"]
                power_on_command = b["pdu_generic"]["power_on_command"]
                device_line += template_device_pdu_generic.substitute(hard_reset_command=hard_reset_command, power_off_command=power_off_command, power_on_command=power_on_command)
            if "uart" in b:
                uart = b["uart"]
                baud = b["uart"].get("baud", baud_default)
                idvendor = b["uart"]["idvendor"]
                idproduct = b["uart"]["idproduct"]
                if type(idproduct) == str:
                    print("Please put hexadecimal IDs for product %s (like 0x%s)" % (board_name,idproduct))
                    sys.exit(1)
                if type(idvendor) == str:
                    print("Please put hexadecimal IDs for vendor %s (like 0x%s)" % (board_name,idvendor))
                    sys.exit(1)
                line = template_conmux.substitute(board=board_name, baud=baud)
                if "serial" in uart:
                    serial = b["uart"]["serial"]
                    udev_line += template_udev_serial.substitute(board=board_name, serial=serial, idvendor="%04x" % idvendor, idproduct="%04x" % idproduct)
                else:
                    devpath = b["uart"]["devpath"]
                    udev_line += template_udev_devpath.substitute(board=board_name, devpath=devpath, idvendor="%04x" % idvendor, idproduct="%04x" % idproduct)
                if "devices" in dockcomp["services"][lab_name]:
                    dc_devices = dockcomp["services"][lab_name]["devices"]
                else:
                    dockcomp["services"][lab_name]["devices"] = []
                    dc_devices = dockcomp["services"][lab_name]["devices"]
                dc_devices.append("/dev/%s:/dev/%s" % (board_name, board_name))
                fp = open("lava-slave/conmux/%s.cf" % board_name, "w")
                fp.write(line)
                fp.close()
                device_line += template_device_conmux.substitute(board=board_name)
            elif "connection_command" in b:
                connection_command = b["connection_command"]
                device_line += template_device_connection_command.substitute(connection_command=connection_command)
            if "macaddr" in b:
                device_line += '{% set uboot_set_mac = true %}'
                device_line += "{%% set uboot_mac_addr = '%s' %%}" % b["macaddr"]
            if "fastboot_serial_number" in b:
                fserial = b["fastboot_serial_number"]
                device_line += "{%% set fastboot_serial_number = '%s' %%}" % fserial

            # board specific hacks
            if devicetype == "qemu" and not use_kvm:
                device_line += "{% set no_kvm = True %}\n"
            if not os.path.isdir("lava-master/devices/"):
                os.mkdir("lava-master/devices/")
            device_path = "lava-master/devices/%s" % lab_name
            if not os.path.isdir(device_path):
                os.mkdir(device_path)
            board_device_file = "%s/%s.jinja2" % (device_path, board_name)
            fp = open(board_device_file, "w")
            fp.write(device_line)
            fp.close()
        if not os.path.isdir("udev"):
            os.mkdir("udev")
        fp = open("udev/99-lavalab-udev-%s.rules" % lab_name, "w")
        fp.write(udev_line)
        fp.close()
        if "dispatcher_ip" in lab:
            fp = open("lava-master/slaves/%s.yaml" % lab_name, "w")
            fp.write("dispatcher_ip: %s" % lab["dispatcher_ip"])
            fp.close()

    #now proceed with tokens
    fp = open(tokens_yaml, "r")
    tokens = yaml.load(fp)
    fp.close()
    if not os.path.isdir("lava-master/users/"):
        os.mkdir("lava-master/users/")
    if not os.path.isdir("lava-master/tokens/"):
        os.mkdir("lava-master/tokens/")
    for section_name in tokens:
        section = tokens[section_name]
        if section_name == "lava_server_users":
            for user in section:
                username = user["name"]
                ftok = open("lava-master/users/%s" % username, "w")
                token = user["token"]
                ftok.write("TOKEN=" + token + "\n")
                if "password" in user:
                    password = user["password"]
                    ftok.write("PASSWORD=" + password + "\n")
                # libyaml convert yes/no to true/false...
                if "staff" in user:
                    value = user["staff"]
                    if value is True:
                        ftok.write("STAFF=1\n")
                if "superuser" in user:
                    value = user["superuser"]
                    if value is True:
                        ftok.write("SUPERUSER=1\n")
                ftok.close()
        if section_name == "callback_tokens":
            for token in section:
                filename = token["filename"]
                ftok = open("lava-master/tokens/%s" % filename, "w")
                username = token["username"]
                ftok.write("USER=" + username + "\n")
                vtoken = token["token"]
                ftok.write("TOKEN=" + vtoken + "\n")
                description = token["description"]
                ftok.write("DESCRIPTION=" + description)
                ftok.close()
    with open('docker-compose.yml', 'w') as f:
        yaml.dump(dockcomp, f)

if __name__ == "__main__":
    shutil.copy("common/build-lava", "lava-slave/scripts/build-lava")
    shutil.copy("common/build-lava", "lava-master/scripts/build-lava")
    parser = argparse.ArgumentParser()
    parser.add_argument("--header", help="use this file as header for output file")
    args = parser.parse_args()
    main(args)

