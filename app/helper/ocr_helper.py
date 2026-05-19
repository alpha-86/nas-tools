class OcrHelper:

    # 远程 OCR 服务 nastool.org 已禁用
    # _ocr_b64_url = "https://nastool.org/captcha/base64"

    def get_captcha_text(self, image_url=None, image_b64=None, cookie=None, ua=None):
        """
        根据图片地址，获取验证码图片，并识别内容
        远程 OCR 服务已禁用，直接返回空字符串。
        :param image_url: 图片地址
        :param image_b64: 图片base64，跳过图片地址下载
        :param cookie: 下载图片使用的cookie
        :param ua: 下载图片使用的ua
        """
        return ""
