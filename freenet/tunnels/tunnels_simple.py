#!/usr/bin/env python3
"""
最简单的tunnel server,采用aes加密
配置文件添加一个字段tunnels_simple
最终形式例如这样
{
...
tunnels_simple:[
    (username,passwd),....
]
...
}

"""

import json, random

import fdslight_etc.fn_server as fns_config
import freenet.handler.tunnels_base as tunnels_base
import freenet.lib.base_proto.over_tcp as over_tcp


class tcp_tunnel(tunnels_base.tcp_tunnels_base):
    __users = None
    # 分配到的IP地址
    __ipaddr = None

    def __send_auth_response(self, is_ok, aes_key=None, ips=None):
        """
        :param is_ok:
        :param aes_key:随机生成的 aes key
        :param ips: 分配到的IP地址列表
        :return:
        """
        if is_ok:
            pydict = {"status": True, "ips": ips, "key": aes_key}
        else:
            pydict = {"status": False}

        auth_data = json.dumps(pydict).encode("utf-8")
        pkt_size = len(auth_data)

        # 向隧道发送数据
        self.send_data(over_tcp.ACT_AUTH, pkt_size, auth_data)

    def __gen_aes_key(self):
        """生成随机AES KEY"""
        sts = "1234567890asdfghjklzxcvbnmQWERTYUIOPASDFGHJKLZXCVBNM"
        max_index = len(sts) - 1
        seq = []

        # 默认加密支持AES-128
        for i in range(16):
            n = random.randint(0, max_index)
            seq.append(sts[n])

        return "".join(seq)

    def fn_handler_init(self):
        """类初始化的时候调用此函数"""
        self.__users = fns_config.configs["tunnels_simple"]

    def fn_on_connect(self, sock, caddr):
        """客户端发生连接时调用此函数,一般不需要更改"""
        self.create_handler(self.fileno, tcp_tunnel, s=sock, c_addr=caddr)
        return True

    def fn_auth(self, byte_data):
        """客户端发送验证的时候会调用此函数
        :param byte_data: 客户端发送的验证数据
        :return Boolean: True表示验证通过,False表示验证失败
        """
        try:
            sts = byte_data.decode("utf-8")
            auth_info = json.loads(sts)
        except:
            self.__send_auth_response(False)
            return False

        uname = auth_info.get("username", "")
        upasswd = auth_info.get("password", "")

        if not uname or not upasswd:
            return False

        is_find = False
        for name, passwd in self.__users:
            if name == uname and passwd == upasswd:
                is_find = True
                break
            continue

        if not is_find:
            self.__send_auth_response(False)
            return False

        # 一定要获取可以分配的IP地址，否则客户端没IP地址,无法进行流量代理
        ips = self.get_client_ips(5)
        aes_key = self.__gen_aes_key()

        self.__send_auth_response(True, aes_key, ips)
        self.encrypt_m.set_aes_key(aes_key)
        self.decrypt_m.set_aes_key(aes_key)

        return True

    def fn_on_recv(self, recv_size):
        """验证成功后客户端发送了数据包之后会调用此函数
        :param recv_size: 客户端的数据包大小
        :return Boolean:True表示继续执行,False表示不执行,即关闭连接
        """
        return True

    def fn_on_send(self, send_size):
        """服务器发送数据包调用此函数
        :param send_size: 服务器发送的数据包大小
        :return Boolean:True表示继续执行,False表示不执行,即关闭连接
        """
        return True

    def fn_handler_clear(self):
        """连接关闭后的资源回收
        :return:
        """
        # 注意回收IP地址
        self.del_client_ips()
        return
