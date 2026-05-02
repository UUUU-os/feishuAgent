with open("/home/lear-ubuntu-22/.gemini/tmp/feishuagent/tool-outputs/session-307d000d-9bc4-4440-ae1d-26d62e4aeb22/run_shell_command_1777624237190_0.txt", "r") as f:
    for line in f:
        if "16:40:" in line and "action_62d05507716e" in line:
            print(line.strip())
