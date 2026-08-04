def read_config(path: str) -> dict:
    with open(path) as f:
        lines = f.readlines()
    config = {}
    for line in lines:
        key, value = line.strip().split("=")
        config[key] = value
    return config
