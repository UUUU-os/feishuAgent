with open("/home/lear-ubuntu-22/.gemini/tmp/feishuagent/tool-outputs/session-307d000d-9bc4-4440-ae1d-26d62e4aeb22/read_background_output_read_background_output_1777624197915_0_zsuwpj.txt", "r") as f:
    for line in f:
        if "reject" in line or "om_x100b50722167eca0b4860167356b1ef" in line:
            print(line.strip())
