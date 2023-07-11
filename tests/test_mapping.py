from app.media.meta import MetaInfo
import os,sys

title = "The Long Season 2017 2160p WEB-DL H265 AAC-XXX"
meta_info = MetaInfo(title=title)
print("cn_name:",meta_info.cn_name)
print("raw_name[%s]en_name[%s]"%(title, meta_info.en_name))
#os.system("touch /config/video_name_mapping.yaml")
os.system("cp /config/video_name_mapping.yaml2 /config/video_name_mapping.yaml")
title = "The Long Season2 2017 2160p WEB-DL H265 AAC-XXX"
meta_info = MetaInfo(title=title)
print("raw_name[%s]en_name[%s]"%(title, meta_info.en_name))
