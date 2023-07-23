#test_encoding.py
import chardet
file_name='video_name_mapping-2.yaml'

right_str = ''
with open(file_name, mode='rb') as sf:
	data = sf.read()
	res = chardet.detect(data)
	print(res)
	right_str = data.decode('gbk')
	print(data.decode('gbk'))

with open(file_name, mode='w') as sf:
	sf.write(right_str)


with open(file_name, mode='r', encoding='utf-8') as sf:
	s = sf.readlines()
	print(s)
