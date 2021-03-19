# @Time    : 2020/9/14
# @Author  : Yuanhang Zhang
# @File    : recorder.py

import socket
import struct
import sys

import time

MSG_VER = 1
MSG_TYPE_LOGIN = 1
MSG_TYPE_DATAREQ = 14

SERVER_IP = '124.16.74.210'
SERVER_PORT = 4520


def send_msg(sock, msgtype, msg):
    # MsgHeader: length (network order), sver (1), msgtype (1, 14), sdata (0)
    nblen = len(msg)
    header = struct.pack('>h', nblen + 8) + \
        struct.pack('hhh', MSG_VER, msgtype, 0)
    msg = header + msg
    sock.sendall(msg)


def recv_msg(sock):
    # Read message header and unpack
    msg_header = recvall(sock, 8)
    if not msg_header:
        return None
    raw_msglen = msg_header[:2]
    msglen = struct.unpack('>h', raw_msglen)[0]
    # Read the message data
    return recvall(sock, msglen - 8)


def recvall(sock, n):
    # Helper function to recv n bytes or return None if EOF is hit
    data = bytearray()
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            return None
        data.extend(packet)
    return data


def parse_hdb_frame(data):
    packet = data[48:]
    # HDB frame head
    idx, ntimetick, nframelength, _, nframerate, nwidth, nheight, _, dwsegment, dwflags, dwpacketnumber, nothers = struct.unpack(
        'iiiiiiiiiiii', data[:48])
    # Invalid data.
    if idx < 0 or idx >= 4:
        return {'ret': -1}
    codec = data[12: 16].decode()
    res = {'ret': 0, 'header': {'codec': codec, 'idx': idx, 'flen': nframelength,
                                'fps': nframerate, 'w': nwidth, 'h': nheight,
                                'seg': dwsegment, 'flags': dwflags, 'tick': ntimetick,
                                'pktno': dwpacketnumber, 'others': nothers}, 'data': packet}

    return res


def setlen(length):
    lower = struct.pack('>i', length * 2 + 1)
    return struct.pack('BBB', 0x80 | ((lower[2] & 0xf0) >> 4), ((lower[2] & 0x0f) << 4) | ((lower[3] & 0xf0) >> 4), ((lower[3] & 0x0f) << 4) | 0x0f)


def pack_adts_frame(data):
    length = len(data)
    header = b'\xff\xf1\x5c' + setlen(length + 7) + b'\xfc'
    return header + data


if __name__ == '__main__':
    recieve_no_data = True
    first_connect = True
    video_fps = [open('vstream{}.h264'.format(i), 'ab', buffering=0) for i in range(2)]
    audio_fp = open('astream.aac', 'ab', buffering=0)
    while recieve_no_data:
        # Initialize socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((SERVER_IP, SERVER_PORT))
        print ('Connected to server')

        # Login
        user_info = b'reach' + b'\x00' * 15 + b'reachplayer' + b'\x00' * 13
        send_msg(s, MSG_TYPE_LOGIN, user_info)
        _ = recv_msg(s)
        print ('Logged in')

        # Select channel
        channel_id = int(sys.argv[1])
        channel_info = struct.pack('i', channel_id)
        send_msg(s, MSG_TYPE_DATAREQ, channel_info)
        _ = recv_msg(s)
        print ('Opened channel')

        if first_connect:
            n_vid_packets = 0
            video_ready = [False for _ in range(2)]
            audio_ready = False
            # NOTE: ticks may not always be available (e.g. 0),
            # so we use packet length to differentiate frames
            prev_flen = -1
            avg_fps = -1
            first_connect = False
        # Receive data packets
        try:
            screen1_time_before = time.time()
            screen2_time_before = time.time()
            audio_time_before = time.time()
            while True:
                # if time.time() > 1600135860: break
                data = recv_msg(s)
                if data is None:
                    break
                # Incoming HDB frame
                if len(data) >= 48:
                    res = parse_hdb_frame(data)
                    if res['ret'] != 0:
                        continue
                    if res['header']['codec'] == 'H264':
                        screen_idx = res['header']['idx']
                        if screen_idx == 0:
                            flen = res['header']['flen']
                            if flen != prev_flen:
                                n_vid_packets += 1
                                prev_flen = flen
                                fps = res['header']['fps']
                                if avg_fps < 0: avg_fps = fps
                                else: avg_fps = 0.95 * avg_fps + 0.05 * fps
                                print ('Progress: {} frames @ {} fps, avg {:.1f} fps, ~{:.2f} sec'.format(
                                    n_vid_packets, fps, avg_fps, n_vid_packets / avg_fps))
                        if not video_ready[screen_idx] and res['header']['seg'] == 2:
                            video_ready[screen_idx] = True
                        if video_ready[screen_idx]:
                            video_fps[screen_idx].write(res['data'])
                    elif res['header']['codec'] == 'ADTS':
                        if not audio_ready and res['header']['seg'] >= 2 and video_ready[0]:
                            audio_ready = True
                        if audio_ready:
                            audio_fp.write(pack_adts_frame(res['data']))

        except KeyboardInterrupt:
            recieve_no_data = False
            print ('Interrupted!')

        s.close()

    for video_fp in video_fps:
        video_fp.close()
    audio_fp.close()
    
    print ('Ref: avg_fps = {:.3f}'.format(avg_fps))
    
