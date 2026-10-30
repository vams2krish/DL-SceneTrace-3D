"""Download 128 original JPEG members using ZIP byte ranges, not the 22 GB archive.

CrossRow: Rinaldi, Gauld, Nic Daeid (2026), DOI 10.15132/10000293.
CC BY-NC-ND 4.0. Local noncommercial research only; do not redistribute derivatives.
"""
import concurrent.futures
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import zipfile
import zlib
import httpx

URL = 'https://s3.eidf.ac.uk/eidf267-crossrow-multimodal-crime-scene-dataset/cmos/iphone-12-pro-max_26mm-equivalent.zip'
DEST = Path('data/crossrow/originals')


def request_range(client, start, end):
    response = client.get(URL, headers={'Range': f'bytes={start}-{end}'})
    response.raise_for_status()
    if response.status_code != 206 or len(response.content) != end-start+1:
        raise ValueError('Server must honor exact byte ranges')
    return response.content


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        response = client.get(URL, headers={'Range':'bytes=-300000'})
        response.raise_for_status()
        if response.status_code != 206:
            raise ValueError('Range downloads required')
        tail=response.content
        # Central directory records are complete in this tail; local offsets are
        # stored in ZipInfo. Build a tiny in-memory ZIP with only its directory.
        eocd=tail.rfind(b'PK\x05\x06')
        fields=struct.unpack_from('<4s4H2LH',tail,eocd)
        directory_size,directory_offset=fields[5],fields[6]
        if directory_offset==0xffffffff or directory_size==0xffffffff:
            zip64=tail.rfind(b'PK\x06\x06')
            if zip64<0:
                raise ValueError('ZIP64 directory metadata unavailable')
            directory_size,directory_offset=struct.unpack_from('<QQ',tail,zip64+40)
        size=int(response.headers['content-range'].split('/')[-1])
        central=request_range(client,directory_offset,directory_offset+directory_size-1)
        end=struct.pack('<4s4H2LH',b'PK\x05\x06',0,0,fields[3],fields[4],directory_size,0,0)
        archive=zipfile.ZipFile(io.BytesIO(central+end))
        members=sorted((m for m in archive.infolist() if m.filename.lower().endswith(('.jpeg','.jpg'))),key=lambda m:m.filename)[:128]
        if len(members)!=128:
            raise ValueError('128 JPEG captures required')

        def download(member):
            destination=DEST/Path(member.filename).name
            if destination.exists():
                content=destination.read_bytes()
            else:
                header=request_range(client,member.header_offset,member.header_offset+29)
                name_size,extra_size=struct.unpack_from('<HH',header,26)
                offset=member.header_offset+30+name_size+extra_size
                compressed=request_range(client,offset,offset+member.compress_size-1)
                if member.compress_type==zipfile.ZIP_STORED:
                    content=compressed
                elif member.compress_type==zipfile.ZIP_DEFLATED:
                    content=zlib.decompress(compressed,-15)
                else:
                    raise ValueError('Unsupported ZIP member compression')
                if len(content)!=member.file_size or zlib.crc32(content)!=member.CRC:
                    raise ValueError('ZIP member integrity check failed')
                destination.write_bytes(content)
            if zlib.crc32(content)!=member.CRC:
                raise ValueError('Existing source differs from archive')
            return {'name':destination.name,'archive_member':member.filename,'bytes':len(content),
                    'sha256':hashlib.sha256(content).hexdigest(),'zip_crc32':f'{member.CRC:08x}'}

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            records=[]
            for result in executor.map(download,members):
                records.append(result)
                print(f'Downloaded {len(records)}/128: {result["name"]}',flush=True)
        metadata={'dataset':'CrossRow: Multimodal Spatial Indoor Crime Scene Dataset',
                  'doi':'10.15132/10000293','creators':['Vincenzo Rinaldi','Dylan Gauld','Niamh Nic Daeid'],
                  'origin':'Real camera captures of a simulated indoor crime scene, not an actual criminal case',
                  'license':'CC BY-NC-ND 4.0','source_archive_url':URL,'archive_bytes':size,
                  'source_etag':response.headers.get('etag'),'selection':'First 128 JPEG filenames in lexical capture order; original bytes',
                  'integrity':'Each extracted member verified against ZIP CRC32; individual SHA-256 recorded',
                  'count':len(records),'sources':records,'publication':'No photographs or adapted reconstructions committed to the public repository'}
        (DEST.parent/'download-provenance.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
        print(json.dumps({'count':len(records),'bytes':sum(r['bytes'] for r in records),'distinct_hashes':len({r['sha256'] for r in records})}),flush=True)


if __name__=='__main__':
    main()
