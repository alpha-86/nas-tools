# NAS媒体库管理工具

基于 [NAStool/nas-tools](https://github.com/NAStool/nas-tools) 的个人维护分支。

## 安装

### Docker

```bash
docker pull alpha8686/nas-tools:latest
```

```bash
docker run -d \
  --name nastools \
  -v /path/to/config:/config \
  -v /path/to/media:/media \
  -p 3000:3000 \
  --restart always \
  alpha8686/nas-tools:latest
```

首次启动后通过 `http://<IP>:3000` 访问 Web 界面进行配置。

## 免责声明

1) 本软件仅供学习交流使用，对用户的行为及内容毫不知情，使用本软件产生的任何责任需由使用者本人承担。
2) 本软件代码开源，基于开源代码进行修改，人为去除相关限制导致软件被分发、传播并造成责任事件的，需由代码修改发布者承担全部责任，不建议对用户认证机制进行规避或修改并公开发布。
3) 本项目没有在任何地方发布捐赠信息页面，也不会接受捐赠或收费，请仔细辨别避免误导。
