#!/usr/bin/python3 -I
"""Generate authentication configuration without editing files in place."""
import argparse
import configparser
import io
from pathlib import Path
import re

PAM_BEGIN = '# BEGIN omarchy-face-auth'
PAM_END = '# END omarchy-face-auth'
SUDO_BEGIN = '# BEGIN omarchy-face-auth plugins'
SUDO_END = '# END omarchy-face-auth plugins'


def insert_block(original, block, begin, end, after_header=False):
    if begin in original or end in original:
        raise ValueError('configuration already contains a face-auth block')
    payload = begin + '\n' + block.rstrip() + '\n' + end + '\n'
    if after_header and original.startswith('#%PAM-1.0\n'):
        return '#%PAM-1.0\n' + payload + original[len('#%PAM-1.0\n'):]
    separator = '' if not original or original.endswith('\n') else '\n'
    return original + separator + payload


def sudo_pam(original, face_block):
    return insert_block(original, face_block, PAM_BEGIN, PAM_END, after_header=True)


def sudo_conf(original):
    roles = set(re.findall(r'^\s*Plugin\s+\S+_(policy|io|audit)\s+', original, re.MULTILINE))
    lines = []
    for role in ('policy', 'io', 'audit'):
        if role not in roles:
            lines.append(f'Plugin sudoers_{role} sudoers.so')
    lines.extend(('Plugin face_audit /usr/lib/security/pam_face_intent.so',
                  'Plugin face_approval /usr/lib/security/pam_face_intent.so'))
    return insert_block(original, '\n'.join(lines), SUDO_BEGIN, SUDO_END)


def howdy_config(original, device):
    if not device.startswith('/dev/') or '\n' in device or '\x00' in device:
        raise ValueError('invalid camera device')
    parser = configparser.ConfigParser()
    parser.read_string(original)
    if not parser.has_section('video') or not parser.has_section('core'):
        raise ValueError('unsupported Howdy configuration')
    parser['video']['device_path'] = device
    parser['core']['disabled'] = 'true'
    parser['core']['no_confirmation'] = 'true'
    output = io.StringIO()
    parser.write(output)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('sudo-pam', 'sudo-conf', 'howdy'))
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--block', type=Path)
    parser.add_argument('--device')
    args = parser.parse_args()
    original = args.source.read_text()
    if args.operation == 'sudo-pam':
        if not args.block:
            parser.error('--block is required')
        result = sudo_pam(original, args.block.read_text())
    elif args.operation == 'sudo-conf':
        result = sudo_conf(original)
    else:
        if not args.device:
            parser.error('--device is required')
        result = howdy_config(original, args.device)
    args.destination.write_text(result)


if __name__ == '__main__':
    main()
