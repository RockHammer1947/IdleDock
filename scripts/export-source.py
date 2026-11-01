"""Export reviewed Git source candidates, without history or local runtime files.

Works before the first commit as well as afterward. This is a local source
snapshot, not a tagged release or a publishing command. Refuses overwrites.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('public_source_check', ROOT/'scripts/check-public.py')
public_source_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(public_source_check)


def export_source(destination):
    destination = Path(destination).resolve()
    manifest_path = destination.with_suffix('.manifest.json')
    checksum_path = destination.with_suffix('.sha256')
    for output in (destination, manifest_path, checksum_path):
        if output.exists():
            raise FileExistsError(f'Refusing to overwrite: {output.name}')
    paths, errors = public_source_check.check()
    if errors:
        raise ValueError('Public-source checks failed: ' + '; '.join(errors))
    if not paths:
        raise ValueError('No public source candidates')
    files = []
    payloads = []
    for relative in paths:
        source = ROOT/relative
        data = source.read_bytes()
        mode = 0o755 if source.stat().st_mode & 0o111 else 0o644
        files.append({'path': relative.as_posix(), 'size': len(data),
                      'sha256': hashlib.sha256(data).hexdigest(), 'mode': oct(mode)})
        payloads.append(data)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for entry, data in zip(files, payloads):
            info = zipfile.ZipInfo('idledock/'+entry['path'], date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | int(entry['mode'], 8)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    # Verify the actual archive against the snapshot bytes before writing proofs.
    with zipfile.ZipFile(destination) as archive:
        if archive.namelist() != ['idledock/'+entry['path'] for entry in files]:
            raise ValueError('Archive member list does not match the source snapshot')
        for entry in files:
            if hashlib.sha256(archive.read('idledock/'+entry['path'])).hexdigest() != entry['sha256']:
                raise ValueError('Archive checksum mismatch: '+entry['path'])
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    manifest = {'format': 'idledock-source-snapshot-v1', 'file_count': len(files),
                'archive_sha256': digest, 'files': files}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    checksum_path.write_text(f'{digest}  {destination.name}\n')
    return {'archive': str(destination), 'manifest': str(manifest_path),
            'checksum': str(checksum_path), 'files': len(files), 'sha256': digest}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'.build/releases/idledock-source.zip')
    args = parser.parse_args()
    print(json.dumps(export_source(args.output), ensure_ascii=False, indent=2))
