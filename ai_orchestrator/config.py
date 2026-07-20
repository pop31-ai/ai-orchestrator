"""Configuration management for AI Orchestrator"""

import json
import os
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any
from pathlib import Path


@dataclass
class AIProviderConfig:
    name: str
    type: str  # ollama, openai_compatible, ollama_remote, custom
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    models: List[str] = None
    timeout: int = 120
    max_tokens: int = 4096
    temperature: float = 0.7
    enabled: bool = True
    priority: int = 0
    extra_params: Dict[str, Any] = None

    def __post_init__(self):
        if self.models is None:
            self.models = []
        if self.extra_params is None:
            self.extra_params = {}


@dataclass
class AgentConfig:
    enabled: bool = True
    allowed_commands: List[str] = None
    blocked_commands: List[str] = None
    allowed_paths: List[str] = None
    blocked_paths: List[str] = None
    max_command_output: int = 10000
    timeout: int = 60
    confirm_dangerous: bool = True
    allowed_domains: List[str] = None
    blocked_domains: List[str] = None

    def __post_init__(self):
        if self.allowed_commands is None:
            self.allowed_commands = ["ls", "dir", "cat", "type", "grep", "find", "ls", "dir", "cat", "type", "grep", "find", "head", "tail", "wc", "wc", "ps", "tasklist", "netstat", "ss", "ping", "curl", "wget", "git", "python", "python3", "node", "npm", "pip", "cargo", "go", "java", "javac", "gcc", "g++", "make", "cmake", "docker", "kubectl", "terraform", "ansible", "jq", "awk", "sed", "cut", "sort", "uniq", "tee", "xargs", "find", "rg", "fd", "bat", "eza", "lsd", "tree", "du", "df", "free", "htop", "top", "ps", "kill", "pkill", "systemctl", "service", "journalctl", "dmesg", "lsblk", "lsusb", "lspci", "lscpu", "lsmem", "dmidecode", "lshw", "inxi", "neofetch", "fastfetch", "htop", "btop", "btm", "btop", "bottom", "zenith", "glances", "htop", "btop", "btm", "zenith", "glances"]
        if self.blocked_commands is None:
            self.blocked_commands = ["rm", "rmdir", "del", "del", "format", "fdisk", "mkfs", "dd", "shred", "wipefs", "mkfs", "fdisk", "cfdisk", "parted", "gdisk", "sgdisk", "parted", "mkfs", "mkfs.ext4", "mkfs.vfat", "mkfs.ntfs", "mkfs.fat", "mkfs.exfat", "mkfs.btrfs", "mkfs.xfs", "mkfs.jfs", "mkfs.reiserfs", "mkfs.minix", "mkfs.msdos", "mkfs.vfat", "mkfs.cramfs", "mkfs.romfs", "mkfs.squashfs", "mkfs.ubifs", "mkfs.jffs2", "mkfs.yaffs2", "mkfs.logfs", "mkfs.f2fs", "mkfs.nilfs2", "mkfs.exofs", "mkfs.omfs", "mkfs.hpfs", "mkfs.affs", "mkfs.ufs", "mkfs.udf", "mkfs.isofs", "mkfs.iso9660", "mkfs.hfs", "mkfs.hfs+", "mkfs.hfsx", "mkfs.apfs", "mkfs.zfs", "mkfs.btrfs", "mkfs.xfs", "mkfs.ext2", "mkfs.ext3", "mkfs.ext4", "mkfs.ext4dev", "mkfs.minix", "mkfs.msdos", "mkfs.vfat", "mkfs.ntfs", "mkfs.ntfs-3g", "mkfs.exfat", "mkfs.f2fs", "mkfs.nilfs2", "mkfs.erofs", "mkfs.romfs", "mkfs.cramfs", "mkfs.squashfs", "mkfs.jffs2", "mkfs.yaffs2", "mkfs.logfs", "mkfs.omfs", "mkfs.hpfs", "mkfs.affs", "mkfs.ufs", "mkfs.udf", "mkfs.iso9660", "mkfs.hfs", "mkfs.hfs+", "mkfs.hfsx", "mkfs.apfs", "mkfs.zfs", "mkfs.btrfs", "mkfs.xfs", "mkfs.ext2", "mkfs.ext3", "mkfs.ext4", "mkfs.ext4dev", "mkfs.minix", "mkfs.msdos", "mkfs.vfat", "mkfs.ntfs", "mkfs.ntfs-3g", "mkfs.exfat", "mkfs.f2fs", "mkfs.nilfs2", "mkfs.erofs", "mkfs.romfs", "mkfs.cramfs", "mkfs.squashfs", "mkfs.jffs2", "mkfs.yaffs2", "mkfs.logfs", "mkfs.omfs", "mkfs.hpfs", "mkfs.affs", "mkfs.ufs", "mkfs.udf", "mkfs.iso9660", "mkfs.hfs", "mkfs.hfs+", "mkfs.hfsx", "mkfs.apfs", "mkfs.zfs", "mkfs.btrfs", "mkfs.xfs", "mkfs.ext2", "mkfs.ext3", "mkfs.ext4", "mkfs.ext4dev", "mkfs.minix", "mkfs.msdos", "mkfs.vfat", "mkfs.ntfs", "mkfs.ntfs-3g", "mkfs.exfat", "mkfs.f2fs", "mkfs.nilfs2", "mkfs.erofs"]
        if self.allowed_paths is None:
            self.allowed_paths = [str(Path.home()), "C:\\Users", "/home", "/tmp", "/tmp", "/var/tmp", "C:\\Temp", "C:\\Windows\\Temp"]
        if self.blocked_paths is None:
            self.blocked_paths = ["/etc", "/boot", "/sys", "/proc", "/dev", "/run", "/root", "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)", "C:\\System Volume Information"]
        if self.allowed_domains is None:
            self.allowed_domains = ["*"]
        if self.blocked_domains is None:
            self.blocked_domains = []


@dataclass
class HistoryConfig:
    max_messages: int = 10000
    max_tokens_per_message: int = 8192
    max_total_tokens: int = 100000
    page_size: int = 50
    auto_summarize_threshold: int = 5000
    summarize_model: str = ""
    compression_ratio: float = 0.3
    enable_vector_search: bool = False
    vector_db_path: str = ""
    enable_compression: bool = True
    compression_model: str = ""
    max_history_age_days: int = 30
    auto_cleanup: bool = True


@dataclass
class AgentConfig:
    enabled: bool = True
    max_steps: int = 10
    timeout: int = 120
    confirm_actions: bool = True
    allowed_tools: List[str] = None
    sandbox_mode: bool = True
    system_prompt: str = "You are a helpful AI assistant."
    model: str = ""
    max_tool_iterations: int = 20
    max_context_tokens: int = 8192
    enable_tools: bool = True

    def __post_init__(self):
        if self.allowed_tools is None:
            self.allowed_tools = ["shell", "file_read", "file_write", "file_edit", "web_search", "web_fetch", "http_request", "code_exec", "file_list", "file_glob", "file_grep"]


@dataclass
class UIConfig:
    theme: str = "dark"
    page_size: int = 50
    max_history_display: int = 100
    virtual_scroll: bool = True
    virtual_item_height: int = 50
    render_buffer: int = 10
    syntax_highlighting: bool = True
    markdown_render: bool = True
    streaming: bool = True
    show_token_count: bool = True
    show_model_info: bool = True
    compact_mode: bool = False
    font_size: int = 14
    font_family: str = "Consolas, 'Courier New', monospace"


@dataclass
class Config:
    providers: Dict[str, AIProviderConfig] = None
    agent: AgentConfig = None
    history: HistoryConfig = None
    agent_config: AgentConfig = None
    ui: UIConfig = None
    active_provider: str = ""
    default_model: str = ""
    log_level: str = "INFO"
    data_dir: str = ""
    cache_dir: str = ""
    temp_dir: str = ""

    def __post_init__(self):
        if self.providers is None:
            self.providers = {}
        if self.agent is None:
            self.agent = AgentConfig()
        if self.history is None:
            self.history = HistoryConfig()
        if self.agent_config is None:
            self.agent_config = AgentConfig()
        if self.ui is None:
            self.ui = UIConfig()
        if not self.data_dir:
            self.data_dir = str(Path.home() / ".ai_orchestrator")
        if not self.cache_dir:
            self.cache_dir = str(Path(self.data_dir) / "cache")
        if not self.temp_dir:
            self.temp_dir = str(Path(self.data_dir) / "tmp")


DEFAULT_PROVIDERS = {
    "ollama_local": AIProviderConfig(
        name="Ollama Local",
        type="ollama",
        base_url="http://localhost:11434",
        model="llama3.2:3b",
        models=["llama3.2:3b", "llama3.2:1b", "llama3.1:8b", "qwen2.5:7b", "qwen2.5:3b", "qwen2.5:1.5b", "phi3.5:3.8b", "phi3.5:latest", "gemma2:2b", "gemma2:9b", "mistral:7b", "mistral:latest", "codellama:7b", "codellama:13b", "deepseek-coder:6.7b", "deepseek-coder:1.3b", "qwen2.5-coder:7b", "qwen2.5-coder:1.5b", "starcoder2:7b", "starcoder2:3b", "starcoder2:15b"],
        enabled=True,
        priority=10,
    ),
    "ollama_remote": AIProviderConfig(
        name="Ollama Remote",
        type="ollama_remote",
        base_url="http://localhost:11434",
        model="llama3.2:3b",
        enabled=False,
        priority=5,
    ),
    "ollama_free": AIProviderConfig(
        name="Ollama Free Models",
        type="ollama",
        base_url="http://localhost:11434",
        model="qwen2.5:1.5b",
        models=["qwen2.5:1.5b", "qwen2.5:0.5b", "phi3.5:3.8b", "phi3.5:latest", "gemma2:2b", "smollm2:135m", "smollm2:360m", "tinyllama:1.1b", "qwen2:0.5b", "llama3.2:1b"],
        enabled=True,
        priority=20,
    ),
    "ollama_coder": AIProviderConfig(
        name="Ollama Code Models",
        type="ollama",
        base_url="http://localhost:11434",
        model="qwen2.5-coder:7b",
        models=["qwen2.5-coder:7b", "qwen2.5-coder:1.5b", "deepseek-coder:6.7b", "deepseek-coder:1.3b", "starcoder2:7b", "starcoder2:3b", "starcoder2:15b", "codellama:7b", "codellama:13b", "codeqwen:7b", "codegemma:7b"],
        enabled=True,
        priority=15,
    ),
    "openai_compatible_free": AIProviderConfig(
        name="OpenAI Compatible (Free)",
        type="openai_compatible",
        base_url="https://api.groq.com/openai/v1",
        api_key="",  # Need to set GROQ_API_KEY
        model="llama-3.1-70b-versatile",
        models=["llama-3.1-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768", "gemma2-9b-it", "llama-3.2-90b-text-preview", "llama-3.2-11b-vision-preview"],
        enabled=False,
        priority=5,
        extra_params={"extra_headers": {"Authorization": "Bearer ${GROQ_API_KEY}"}}
    ),
    "openrouter_free": AIProviderConfig(
        name="OpenRouter Free",
        type="openai_compatible",
        base_url="https://openrouter.ai/api/v1",
        api_key="",  # Need OPENROUTER_API_KEY
        model="meta-llama/llama-3.2-3b-instruct:free",
        models=["meta-llama/llama-3.2-3b-instruct:free", "microsoft/phi-3-mini-128k-instruct:free", "google/gemma-2-9b-it:free", "mistralai/mistral-7b-instruct:free", "qwen/qwen-2.5-7b-instruct:free", "meta-llama/llama-3.1-8b-instruct:free"],
        enabled=False,
        priority=3,
        extra_params={"extra_headers": {"HTTP-Referer": "https://github.com/ai-orchestrator", "X-Title": "AI Orchestrator"}}
    ),
    "huggingface_free": AIProviderConfig(
        name="HuggingFace Inference (Free)",
        type="openai_compatible",
        base_url="https://api-inference.huggingface.co/models",
        api_key="",  # Need HF_TOKEN
        model="meta-llama/Meta-Llama-3.1-8B-Instruct",
        models=["meta-llama/Meta-Llama-3.1-8B-Instruct", "mistralai/Mistral-7B-Instruct-v0.3", "Qwen/Qwen2.5-7B-Instruct", "google/gemma-2-9b-it", "microsoft/Phi-3.5-mini-instruct"],
        enabled=False,
        priority=2,
    ),
    "lmstudio": AIProviderConfig(
        name="LM Studio Local",
        type="openai_compatible",
        base_url="http://localhost:1234/v1",
        api_key="lm-studio",
        model="local-model",
        models=[],
        enabled=False,
        priority=8,
    ),
    "custom_llama_cpp": AIProviderConfig(
        name="llama.cpp Server",
        type="openai_compatible",
        base_url="http://localhost:8080/v1",
        api_key="",
        model="local",
        models=[],
        enabled=False,
        priority=7,
    ),
    "local_tinyllama": AIProviderConfig(
        name="TinyLlama (Built-in)",
        type="local_ctransformers",
        model="tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
        enabled=True,
        priority=100,
        extra_params={
            "hf_repo": "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
            "hf_file": "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
            "model_type": "llama",
            "repetition_penalty": 1.15,
            "repeat_last_n": 64,
        }
    ),
    "local_tinyllama_q2": AIProviderConfig(
        name="TinyLlama Q2_K (Fast)",
        type="local_ctransformers",
        model="tinyllama-1.1b-chat-v1.0.Q2_K.gguf",
        enabled=True,
        priority=90,
        extra_params={
            "hf_repo": "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
            "hf_file": "tinyllama-1.1b-chat-v1.0.Q2_K.gguf",
            "model_type": "llama",
            "repetition_penalty": 1.15,
            "repeat_last_n": 64,
        }
    ),
    "local_tinyllama_q3": AIProviderConfig(
        name="TinyLlama Q3_K (Balanced)",
        type="local_ctransformers",
        model="tinyllama-1.1b-chat-v1.0.Q3_K_M.gguf",
        enabled=True,
        priority=80,
        extra_params={
            "hf_repo": "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
            "hf_file": "tinyllama-1.1b-chat-v1.0.Q3_K_M.gguf",
            "model_type": "llama",
            "repetition_penalty": 1.15,
            "repeat_last_n": 64,
        }
    ),
    "local_tinyllama_q5": AIProviderConfig(
        name="TinyLlama Q5_K (Quality)",
        type="local_ctransformers",
        model="tinyllama-1.1b-chat-v1.0.Q5_K_M.gguf",
        enabled=True,
        priority=70,
        extra_params={
            "hf_repo": "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
            "hf_file": "tinyllama-1.1b-chat-v1.0.Q5_K_M.gguf",
            "model_type": "llama",
            "repetition_penalty": 1.15,
            "repeat_last_n": 64,
        }
    ),
    "local_mistral7b": AIProviderConfig(
        name="Mistral 7B (Smart)",
        type="local_ctransformers",
        model="Mistral-7B-Instruct-v0.3.Q4_K_M.gguf",
        enabled=True,
        priority=55,
        extra_params={
            "hf_repo": "MaziyarPanahi/Mistral-7B-Instruct-v0.3-GGUF",
            "hf_file": "Mistral-7B-Instruct-v0.3.Q4_K_M.gguf",
            "model_type": "llama",
            "template": "mistral",
            "repetition_penalty": 1.1,
            "repeat_last_n": 64,
            "n_ctx": 4096,
        }
    ),
    "local_tinyllama_q8": AIProviderConfig(
        name="TinyLlama Q8_0 (Best)",
        type="local_ctransformers",
        model="tinyllama-1.1b-chat-v1.0.Q8_0.gguf",
        enabled=True,
        priority=60,
        extra_params={
            "hf_repo": "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
            "hf_file": "tinyllama-1.1b-chat-v1.0.Q8_0.gguf",
            "model_type": "llama",
            "repetition_penalty": 1.15,
            "repeat_last_n": 64,
        }
    ),
}


def load_config(config_path: str = None) -> Config:
    """Load configuration from file or create default"""
    config = Config()
    config.providers = DEFAULT_PROVIDERS.copy()

    if config_path and Path(config_path).exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Merge configs
        for key, value in data.items():
            if key == 'providers':
                for k, v in value.items():
                    if k in config.providers:
                        config.providers[k] = AIProviderConfig(**v)
                    else:
                        config.providers[k] = AIProviderConfig(**v)
            elif key == 'agent':
                config.agent = AgentConfig(**value)
            elif key == 'history':
                config.history = HistoryConfig(**value)
            elif key == 'agent_config':
                config.agent_config = AgentConfig(**value)
            elif key == 'ui':
                config.ui = UIConfig(**value)
            elif hasattr(config, key):
                setattr(config, key, value)

    # Set defaults if not configured - prefer TinyLlama for fast startup
    if not config.active_provider:
        if 'local_tinyllama' in config.providers:
            config.active_provider = 'local_tinyllama'
            config.default_model = config.providers['local_tinyllama'].model

    # Disable Ollama by default (will show connection errors)
    for k in ['ollama_local', 'ollama_free', 'ollama_coder']:
        if k in config.providers:
            config.providers[k].enabled = False

    # Ensure data directories exist
    Path(config.data_dir).mkdir(parents=True, exist_ok=True)
    Path(config.cache_dir).mkdir(parents=True, exist_ok=True)
    Path(config.temp_dir).mkdir(parents=True, exist_ok=True)

    return config


def save_config(config: Config, config_path: str):
    """Save configuration to file"""
    data = {
        'providers': {k: asdict(v) for k, v in config.providers.items()},
        'agent': asdict(config.agent),
        'history': asdict(config.history),
        'agent_config': asdict(config.agent_config),
        'ui': asdict(config.ui),
        'active_provider': config.active_provider,
        'default_model': config.default_model,
        'log_level': config.log_level,
        'data_dir': config.data_dir,
        'cache_dir': config.cache_dir,
        'temp_dir': config.temp_dir,
    }
    Path(config_path).parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_default_config_path() -> str:
    return str(Path.home() / ".ai_orchestrator" / "config.json")