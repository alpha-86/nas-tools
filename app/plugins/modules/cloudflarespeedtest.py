import os
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.plugins import EventManager
from app.plugins.modules._base import _IPluginModule
from app.utils import SystemUtils, RequestUtils, IpUtils
from app.utils.types import EventType
from config import Config


class CloudflareSpeedTest(_IPluginModule):
    # 插件名称
    module_name = "Cloudflare IP优选"
    # 插件描述
    module_desc = "🌩 测试 Cloudflare CDN 延迟和速度，自动优选IP。"
    # 插件图标
    module_icon = "cloudflare.jpg"
    # 主题色
    module_color = "#F6821F"
    # 插件版本
    module_version = "1.0"
    # 插件作者
    module_author = "thsrite"
    # 作者主页
    author_url = "https://github.com/thsrite"
    # 插件配置项ID前缀
    module_config_prefix = "cloudflarespeedtest_"
    # 加载顺序
    module_order = 12
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    eventmanager = None
    _customhosts = False
    _cf_ip = None
    _scheduler = None
    _cron = None
    _onlyonce = False
    _ipv4 = False
    _ipv6 = False
    _version = None
    _additional_args = None
    _re_install = False
    _notify = False
    _check = False
    _cf_path = None
    _cf_ipv4 = None
    _cf_ipv6 = None
    _result_file = None
    _binary_name = 'CloudflareST'

    # 退出事件
    _event = Event()

    @staticmethod
    def get_fields():
        return [
            # 同一板块
            {
                'type': 'div',
                'content': [
                    # 同一行
                    [
                        {
                            'title': '优选IP',
                            'required': "required",
                            'tooltip': '第一次使用，请先将 自定义Hosts插件 中所有 Cloudflare CDN IP 统一改为一个 IP。后续会自动变更。需搭配[自定义Hosts]插件使用',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'cf_ip',
                                    'placeholder': '121.121.121.121',
                                }
                            ]
                        },
                        {
                            'title': '优选周期',
                            'required': "required",
                            'tooltip': 'Cloudflare CDN优选周期，支持5位cron表达式',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'cron',
                                    'placeholder': '0 0 0 ? *',
                                }
                            ]
                        },
                        {
                            'title': 'CloudflareSpeedTest版本',
                            'required': "",
                            'tooltip': '如当前版本与CloudflareSpeedTest最新版本不一致，可开启重装后运行获取新版本',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'version',
                                    'placeholder': '暂未安装',
                                }
                            ]
                        }
                    ],
                    [
                        {
                            'title': 'IPv4',
                            'required': "",
                            'tooltip': '优选测速ipv4；v4和v6必须其一，都不选择则默认ipv4',
                            'type': 'switch',
                            'id': 'ipv4',
                        },
                        {
                            'title': 'IPv6',
                            'required': "",
                            'tooltip': '优选测速ipv6；v4和v6必须其一，都不选择则默认ipv4。选择ipv6会大大加长测速时间。',
                            'type': 'switch',
                            'id': 'ipv6',
                        },
                        {
                            'title': '自动校准',
                            'required': "",
                            'tooltip': '开启后，会自动查询自定义hosts插件中出现次数最多的ip替换到优选IP。（如果出现次数最多的ip不止一个，则不做兼容处理）',
                            'type': 'switch',
                            'id': 'check',
                        },
                    ],
                    [
                        {
                            'title': '立即运行一次',
                            'required': "",
                            'tooltip': '打开后立即运行一次（点击此对话框的确定按钮后即会运行，周期未设置也会运行），关闭后将仅按照优选周期运行（同时上次触发运行的任务如果在运行中也会停止）',
                            'type': 'switch',
                            'id': 'onlyonce',
                        },
                        {
                            'title': '重装后运行',
                            'required': "",
                            'tooltip': '开启后，每次会重新下载CloudflareSpeedTest，网络不好慎选',
                            'type': 'switch',
                            'id': 're_install',
                        },
                        {
                            'title': '运行时通知',
                            'required': "",
                            'tooltip': '运行任务后会发送通知（需要打开插件消息通知）',
                            'type': 'switch',
                            'id': 'notify',
                        },
                    ]
                ]
            },
            {
                'type': 'details',
                'summary': '高级参数',
                'tooltip': 'CloudflareSpeedTest的高级参数，请勿随意修改（请勿新增-f -o参数）',
                'content': [
                    [
                        {
                            'required': "",
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'additional_args',
                                    'placeholder': '-dd'
                                }
                            ]
                        }
                    ]
                ]
            }
        ]

    @staticmethod
    def get_script():
        """
        返回插件额外的JS代码
        """
        return """
        $(document).ready(function () {
          $('#cloudflarespeedtest_version').prop('disabled', true);
        });
         """

    def init_config(self, config=None):
        self.eventmanager = EventManager()

        # 读取配置
        if config:
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron")
            self._cf_ip = config.get("cf_ip")
            self._version = config.get("version")
            self._ipv4 = config.get("ipv4")
            self._ipv6 = config.get("ipv6")
            self._re_install = config.get("re_install")
            self._additional_args = config.get("additional_args")
            self._notify = config.get("notify")
            self._check = config.get("check")

        # 停止现有任务
        self.stop_service()

        # 启动定时任务 & 立即运行一次
        if self.get_state() or self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=Config().get_timezone())
            if self._cron:
                self.info(f"Cloudflare CDN优选服务启动，周期：{self._cron}")
                self._scheduler.add_job(self.__cloudflareSpeedTest, CronTrigger.from_crontab(self._cron))

            if self._onlyonce:
                self.info(f"Cloudflare CDN优选服务启动，立即运行一次")
                self._scheduler.add_job(self.__cloudflareSpeedTest, 'date',
                                        run_date=datetime.now(tz=pytz.timezone(Config().get_timezone())) + timedelta(
                                            seconds=3))
                # 关闭一次性开关
                self._onlyonce = False
                self.__update_config()

            if self._cron or self._onlyonce:
                # 启动服务
                self._scheduler.print_jobs()
                self._scheduler.start()

    def __cloudflareSpeedTest(self):
        """
        CloudflareSpeedTest优选
        """
        self._cf_path = self.get_data_path()
        self._cf_ipv4 = os.path.join(self._cf_path, "ip.txt")
        self._cf_ipv6 = os.path.join(self._cf_path, "ipv6.txt")
        self._result_file = os.path.join(self._cf_path, "result_hosts.txt")

        # 获取自定义Hosts插件，若无设置则停止
        customHosts = self.get_config("CustomHosts")
        self._customhosts = customHosts and customHosts.get("enable")
        if self._cf_ip and not customHosts or not customHosts.get("hosts"):
            self.error(f"Cloudflare CDN优选依赖于自定义Hosts，请先维护hosts")
            return

        if not self._cf_ip:
            self.error("CloudflareSpeedTest加载成功，首次运行，需要配置优选ip")
            return

        # ipv4和ipv6必须其一
        if not self._ipv4 and not self._ipv6:
            self._ipv4 = True
            self.__update_config()
            self.warn(f"Cloudflare CDN优选未指定ip类型，默认ipv4")

        err_flag, release_version = self.__check_envirment()
        if err_flag and release_version:
            # 更新版本
            self._version = release_version
            self.__update_config()

        hosts = customHosts.get("hosts")
        if isinstance(hosts, str):
            hosts = str(hosts).split('\n')

        # 校正优选ip
        if self._check:
            self.__check_cf_if(hosts=hosts)

        def _apply_best_ip(best_ip):
            """将优选后的 best_ip 应用到自定义Hosts插件"""
            if not (IpUtils.is_ipv4(best_ip) or IpUtils.is_ipv6(best_ip)):
                return False
            if best_ip == self._cf_ip:
                self.info(f"CloudflareSpeedTest CDN优选ip未变，不做处理")
                return True
            err_hosts = customHosts.get("err_hosts")
            enable = customHosts.get("enable")
            new_hosts = []
            for host in hosts:
                if host and host != '\n':
                    host_arr = str(host).split()
                    if host_arr[0] == self._cf_ip:
                        new_hosts.append(host.replace(self._cf_ip, best_ip))
                    else:
                        new_hosts.append(host)
            self.update_config({
                "hosts": new_hosts,
                "err_hosts": err_hosts,
                "enable": enable
            }, "CustomHosts")
            old_ip = self._cf_ip
            self._cf_ip = best_ip
            self.__update_config()
            self.info(f"Cloudflare CDN优选ip [{best_ip}] 已替换自定义Hosts插件")
            self.info("通知CustomHosts插件重载 ...")
            self.eventmanager.send_event(EventType.PluginReload,
                                         {"plugin_id": "CustomHosts"})
            if self._notify:
                self.send_message(
                    title="【Cloudflare优选任务完成】",
                    text=f"原ip：{old_ip}\n新ip：{best_ip}"
                )
            return True

        def _read_result_csv(path):
            """用 Python 解析结果文件第二行第一列（CSV 格式），避免 shell 注入"""
            import csv
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    next(reader, None)  # 跳过表头
                    row = next(reader, None)
                    if row:
                        return row[0].strip()
            except Exception:
                pass
            return None

        # 开始优选
        if err_flag:
            # P0：禁用自动执行外部二进制。若已有手动执行的结果文件，直接读取应用
            if Path(self._result_file).exists():
                best_ip = _read_result_csv(self._result_file)
                if best_ip:
                    self.info(f"\n读取到已有最优ip==>[{best_ip}]")
                    _apply_best_ip(best_ip)
                else:
                    self.error(f"结果文件 {self._result_file} 解析失败或为空")
                return

            self.info("正在进行CLoudflare CDN优选，请耐心等待")
            cf_command = f'cd {self._cf_path} && ./{self._binary_name} {self._additional_args} -o {self._result_file}' + (
                f' -f {self._cf_ipv4}' if self._ipv4 else '') + (f' -f {self._cf_ipv6}' if self._ipv6 else '')
            self.error("CloudflareSpeedTest 自动执行已禁用（P0 供应链安全硬化）")
            self.error(f"请手动执行以下命令：{cf_command}")
            self.error(f"然后将结果写入 {self._result_file} 后重新运行插件")
            return
        else:
            self.error("获取到最优ip格式错误，请重试")
            self._onlyonce = False
            self.__update_config()
            self.stop_service()

    def __check_cf_if(self, hosts):
        """
        校正cf优选ip
        防止特殊情况下cf优选ip和自定义hosts插件中ip不一致
        """
        # 统计每个IP地址出现的次数
        ip_count = {}
        for host in hosts:
            ip = host.split()[0]
            if ip in ip_count:
                ip_count[ip] += 1
            else:
                ip_count[ip] = 1

        # 找出出现次数最多的IP地址
        max_ips = []  # 保存最多出现的IP地址
        max_count = 0
        for ip, count in ip_count.items():
            if count > max_count:
                max_ips = [ip]  # 更新最多的IP地址
                max_count = count
            elif count == max_count:
                max_ips.append(ip)

        # 如果出现次数最多的ip不止一个，则不做兼容处理
        if len(max_ips) != 1:
            return

        if max_ips[0] != self._cf_ip:
            self._cf_ip = max_ips[0]
            self.info(f"获取到自定义hosts插件中ip {max_ips[0]} 出现次数最多，已自动校正优选ip")

    def __check_envirment(self):
        """
        环境检查
        """
        # P0：禁用自动下载。若二进制不存在，提示用户手动放置
        if not Path(f'{self._cf_path}/{self._binary_name}').exists():
            self.error(f"CloudflareSpeedTest 二进制不存在，请手动下载并放置到 {self._cf_path}")
            return False, None
        return True, self._version

    def __os_install(self, download_url, cf_file_name, release_version, unzip_command):
        """
        自动下载安装已禁用（P0 供应链安全硬化）
        """
        # P0：禁用自动下载外部二进制
        self.error("自动下载安装 CloudflareSpeedTest 已禁用，请手动下载并放置二进制")
        return False, None

    def __update_config(self):
        """
        更新优选插件配置
        """
        self.update_config({
            "onlyonce": False,
            "cron": self._cron,
            "cf_ip": self._cf_ip,
            "version": self._version,
            "ipv4": self._ipv4,
            "ipv6": self._ipv6,
            "re_install": self._re_install,
            "additional_args": self._additional_args,
            "notify": self._notify,
            "check": self._check
        })

    def get_state(self):
        return self._cf_ip and True if self._cron else False

    def stop_service(self):
        """
          退出插件
          """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            print(str(e))
