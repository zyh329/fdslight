#!/usr/bin/env python3
"""协议帧格式
session_id: 2 bytes 会话ID
real_length:2 bytes 实际的数据长度
pkt_id: 2 bytes 包ID
tot_seg: 4 bit 全部的分包个数
seq: 4 bit 当前分包序号
reverse:4 bit 保留
action:4bit 动作
"""

ACT_AUTH = 1
ACT_PING = 2
ACT_PONG = 3
ACT_CLOSE = 4
ACT_DATA = 5
ACT_DNS = 6

ACTS = (
    ACT_AUTH, ACT_PING, ACT_PONG,
    ACT_CLOSE, ACT_DATA, ACT_DNS,
)

MIN_FIXED_HEADER_SIZE = 8


class builder(object):
    __session_id = 0
    __fixed_header_size = 0
    __pkt_id = 1
    # 数据块大小
    __block_size = 1210

    def __init__(self, fixed_header_size):
        if fixed_header_size < MIN_FIXED_HEADER_SIZE: raise ValueError(
            "the header size can not less than %s" % MIN_FIXED_HEADER_SIZE)
        self.__fixed_header_size = fixed_header_size

    def set_session_id(self, session_id):
        self.__session_id = session_id

    @property
    def block_size(self):
        return self.__block_size

    def __gen_raib(self, block_a, block_b):
        """生成冗余数据块,类似于磁盘阵列的RAID5模式,较少丢包率
        """
        size_a = len(block_a)
        size_b = len(block_b)

        list_a = list(block_a)
        list_b = list(block_b)

        L = None
        if size_a > size_b:
            L = list_b
        else:
            L = list_a
        n = abs(size_a - size_b)
        for i in range(n): L.append(0)
        csum_list = []
        cnt = 0
        for n in list_a:
            csum = n ^ list_b[cnt]
            cnt += 1
            csum_list.append(csum)

        return (bytes(list_a), bytes(list_b), bytes(csum_list),)

    def __build_proto_header(self, real_size, tot_seg, seq, action):
        if action not in ACTS: raise ValueError("not support action type")
        L = (
            (self.__session_id & 0xff00) >> 8, self.__session_id & 0x00ff,
            (real_size & 0xff00) >> 8, real_size & 0x00ff,
            (self.__pkt_id & 0xff00) >> 8, self.__pkt_id & 0x00ff,
            (tot_seg << 4) | seq,
            action,
        )

        if tot_seg == seq:
            if self.__pkt_id == 65535: self.__pkt_id = 0
            self.__pkt_id += 1

        return bytes(L)

    def __get_sent_raw_data(self, data_len, byte_data):
        """获取要发送的原始数据"""
        data_block_size = self.__block_size - self.__fixed_header_size
        tmplist = []
        b, e = (0, data_block_size,)

        if data_len == 0: return [b"", ]

        while b < data_len:
            t = byte_data[b:e]
            b = e
            e += data_block_size
            tmplist.append(t)

        ret_v = None
        # 如果有2个数据块,那么启用数据冗余,减少丢包率
        if len(tmplist) == 2:
            a, b = tuple(tmplist)
            ret_v = self.__gen_raib(a, b)
        else:
            # 只有一个数据块那么就不启用数据冗余
            ret_v = tuple(tmplist)
        return ret_v

    def build_packets(self, action, data_len, byte_data):
        if data_len > 1500: raise ValueError("the value of data must be less than 1500")
        data_seq = []
        tmp_t = self.__get_sent_raw_data(data_len, byte_data)
        tot_seq = len(tmp_t)
        seq = 1
        for block in tmp_t:
            size = len(block)
            base_header = self.__build_proto_header(size, tot_seq, seq, action)
            e_hdr = self.wrap_header(base_header)
            e_body = self.wrap_body(size, block)
            data_seq.append(b"".join((e_hdr, e_body,)))
            seq += 1

        return data_seq

    def set_max_pkt_size(self, size):
        """单个UDP数据包所能传输的数据大小"""
        min_size = 1000 + self.__fixed_header_size
        if size < min_size: raise ValueError("the value of size must not be less than %s" % min_size)
        self.__block_size = size

    def wrap_header(self, base_hdr):
        """重写这个方法"""
        pass

    def wrap_body(self, size, body_data):
        """重写这个方法"""
        pass

    @property
    def fixed_header_size(self):
        return self.__fixed_header_size

    def build_ping(self):
        """
        重写这个方法
        """
        pass

    def build_pong(self):
        """
        重写这个方法
        """
        pass

    def build_close(self):
        """
        重写这个方法
         """
        pass

    def reset(self):
        """
        重写这个方法
        """
        pass


class parser(object):
    __fixed_header_size = 0
    __pkt_id = 0
    __data_area = None
    # 总共的段数
    __tot_seg = 0

    def __init__(self, fixed_header_size):
        if fixed_header_size < MIN_FIXED_HEADER_SIZE: raise ValueError(
            "the header size can not less than %s" % MIN_FIXED_HEADER_SIZE)

        self.__fixed_header_size = fixed_header_size
        self.__wait_fill_seq = []
        self.__data_area = {}

    def __parse_raib(self, data_block, csum_block):
        """从数据块和校检块中获取另一数据块内容"""
        cnt = 0
        tmp_list = []
        for n in data_block:
            tmp_list.append(n ^ csum_block[cnt])
            cnt += 1

        return bytes(tmp_list)

    def __parse_header(self, header):
        session_id = (header[0] << 8) | header[1]
        real_length = (header[2] << 8) | header[3]
        pkt_id = (header[4] << 8) | header[5]
        seg_info = header[6]

        tot_seg = (seg_info & 0xf0) >> 4
        seq = seg_info & 0x0f

        action = header[7] & 0x0f

        return (session_id, real_length, pkt_id, tot_seg, seq, action,)

    def __get_ip4_pkt(self, pkt):
        tot_len = (pkt[2] << 8) | pkt[3]
        return pkt[0:tot_len]

    def parse(self, packet):
        real_header = self.unwrap_header(packet[0:self.__fixed_header_size])
        if not real_header: return
        session_id, length, pkt_id, tot_seg, seq, action = self.__parse_header(real_header)
        real_body = self.unwrap_body(length, packet[self.__fixed_header_size:])

        if seq == 3 and not self.__pkt_id: return
        if seq > 3: return b""
        if pkt_id == 0: return b""
        # 如果只有一个数据包,那么直接返回
        if tot_seg == 1:
            self.reset()
            return (session_id, action, real_body,)
        if pkt_id != self.__pkt_id and self.__pkt_id != 0: self.reset()
        # 最大分段只能是3段
        if tot_seg > 3: return None
        self.__data_area[seq] = real_body

        if 1 in self.__data_area and 2 in self.__data_area:
            pkt = b"".join((self.__data_area[1], self.__data_area[2],))
            self.reset()
            return (session_id, action, self.__get_ip4_pkt(pkt),)
        if len(self.__data_area) == 2:
            result = self.__get_data_from_raib()
            self.reset()
            return (session_id, action, self.__get_ip4_pkt(result),)

        self.__pkt_id = pkt_id
        return None

    def __get_data_from_raib(self):
        data_a = None
        n = 0

        if 1 in self.__data_area:
            data_a = self.__data_area[1]
            n = 1

        if 2 in self.__data_area:
            data_a = self.__data_area[2]
            n = 2

        len_a = len(data_a)
        data_b = self.__data_area[3]
        len_b = len(data_b)

        if len_a != len_b:
            self.reset()
            return b""

        data_c = self.__parse_raib(data_a, data_b)
        iter_obj = None
        if n == 1: iter_obj = (data_a, data_c,)
        if n == 2: iter_obj = (data_c, data_a,)

        return b"".join(iter_obj)

    def unwrap_header(self, header_data):
        """
        解包头, 重写这个方法
        """
        pass

    def unwrap_body(self, real_size, body_data):
        """
        重写这个方法
        """
        pass

    def reset(self):
        """
        重写这个方法,该reset无需手动调用
        """
        self.__tot_seg = 0
        self.__data_area = {}
        self.__pkt_id = 0
