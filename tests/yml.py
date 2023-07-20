import ruamel.yaml
config_path='1.yml'
config=None
with open(config_path, mode='r', encoding='utf-8') as cf:
    try:
        config = ruamel.yaml.YAML().load(cf)
        print(type(config))
    except Exception as e:
        print("exception:%s"%(str(e)))

print(config)
vvv=config.get("abc2")
print(vvv)
