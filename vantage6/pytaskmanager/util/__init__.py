import sys
import os, os.path
import pprint
import pytaskmanager.util.Colorer
import logging
import logging.handlers
import appdirs
import yaml

from schema import SchemaError
from pathlib import Path
from sqlalchemy.engine.url import make_url
from weakref import WeakValueDictionary

from pytaskmanager import APPNAME
from pytaskmanager.util.context import validate_configuration
from pytaskmanager.util.Configuration import ( ConfigurationManager, 
    ServerConfigurationManager, NodeConfigurationManager ) 


class Singleton(type):
    _instances = WeakValueDictionary()

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            instance = super(Singleton, cls).__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]


class AppContext(metaclass=Singleton):

    INST_CONFIG_MANAGER = ConfigurationManager
    
    def __init__(self, instance_type, instance_name, system_folders=False,
        environment="application"):
        """instance name is equal to the config-filename..."""

        # lookup system / user directories
        self.set_folders(instance_type, instance_name, system_folders)

        # configuration environment, load a single configuration from 
        # entire confiration file (which can contain multiple environments) 
        self.config_file = self.config_dir / (instance_name + ".yaml")
        
        # will load a specific environment in the config_file, this 
        # triggers to set the logging as this is env dependant
        self.environment = environment

    def set_folders(self, instance_type, instance_name, system_folders):
        dirs = self.instance_folders(instance_type, instance_name, 
            system_folders)
        self.log_dir = dirs.get("log")
        self.data_dir = dirs.get("data")
        self.config_dir = dirs.get("config")
        
    def setup_logging(self):
        """Setup a basic logging mechanism."""
     
        log_config = self.config["logging"]
             
        level = getattr(logging, log_config["level"].upper())
        format_ = log_config["format"] 
        datefmt = log_config.get("datefmt", "")

        # make sure the log-file exists
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        
        # Create the root logger
        logger = logging.getLogger()
        logger.setLevel(level)
    
        # Create RotatingFileHandler
        rfh = logging.handlers.RotatingFileHandler(
            self.log_file, 
            maxBytes=1024*log_config["max_size"], 
            backupCount=log_config["backup_count"]
        )
        rfh.setLevel(level)
        rfh.setFormatter(logging.Formatter(format_, datefmt))
        logger.addHandler(rfh)
        
        # Check what to do with the console output ...
        if log_config["use_console"]:
            ch = logging.StreamHandler(sys.stdout)
            ch.setLevel(level)
            ch.setFormatter(logging.Formatter(format_, datefmt))
            logger.addHandler(ch)
            
        # Finally, capture all warnings using the logging mechanism.
        logging.captureWarnings(True)

        module_name = __name__.split('.')[-1]
        log = logging.getLogger(module_name)
        
        # Make some history
        log.info("#" * 80)
        log.info(f'#{APPNAME:^78}#')
        log.info("#" * 80)
        log.info(f"Started application {APPNAME} with environment {self.environment}")
        log.info("Current working directory is '%s'" % os.getcwd())
        log.info("Succesfully loaded configuration from '%s'" % self.config_file)
        log.info("Logging to '%s'" % self.log_file)

    @property
    def log_file(self):
        return self.log_dir / (self.config_manager.name + ".log")

    @property
    def config_file(self):
        return self.__config_file
    
    @config_file.setter
    def config_file(self, path):
        assert Path(path).exists(), f"config {path} not found" 
        self.__config_file = Path(path)
        self.config_manager = self.INST_CONFIG_MANAGER.from_file(path)
        
    @property
    def environment(self):
        return self.__environment
    
    @environment.setter
    def environment(self, env):
        assert self.config_manager, \
            "Environment set before ConfigurationManager is initialized..."
        assert env in self.config_manager.available_environments, \
            f"Requested environment {env} is not found in the configuration"
        self.__environment = env
        self.config = self.config_manager.get(env)
        self.setup_logging()

    @classmethod
    def from_external_config_file(cls, path, instance_type, 
        environment="application", system_folders=False):
        instance_name = Path(path).stem
        self = cls.__new__(cls)
        self.set_folders(instance_type, instance_name, system_folders)
        self.config_dir = Path(path).parent
        self.config_file = path
        self.environment = environment
        return self

    @classmethod
    def config_exists(cls, instance_type, instance_name, environment="application", 
        system_folders=False):
        
        # obtain location of config file
        d = appdirs.AppDirs(APPNAME, "")
        config_dir = d.site_config_dir if system_folders else d.user_config_dir
        config_file = Path(config_dir) / instance_type / (instance_name+".yaml")
        if not Path(config_file).exists():
            return False

        # check that environment is present in config-file
        config_manager = cls.INST_CONFIG_MANAGER.from_file(config_file)
        return bool(getattr(config_manager, environment))

    @staticmethod
    def instance_folders(instance_type, instance_name, system_folders):
        d = appdirs.AppDirs(APPNAME, "")
        if system_folders:
            return {
                "log":Path(d.site_data_dir) / instance_type,
                "data":Path(d.site_data_dir) / instance_type / instance_name,
                "config":Path(d.site_config_dir) / instance_type
            }
        else:
            return {
                "log":Path(d.user_log_dir) / instance_type,
                "data":Path(d.user_data_dir) / instance_type / instance_name,
                "config":Path(d.user_config_dir) / instance_type
            }



class NodeContext(AppContext):
    
    INST_CONFIG_MANAGER = NodeConfigurationManager

    def __init__(self, instance_name, environment="application", system_folders=False):
        super().__init__("node", instance_name, environment=environment, 
            system_folders=system_folders)
    
    def get_database_uri(self, label="default"):
        return self.config["databases"][label]

    @classmethod
    def from_external_config_file(cls, path, environment="application", system_folders=False):
        return super().from_external_config_file(
            path, "node", environment, system_folders
        )

    @staticmethod
    def config_exists(instance_name, environment="application", system_folders=False):
        return AppContext.config_exists("node", 
            instance_name, environment= environment, system_folders=system_folders)
        

class ServerContext(AppContext):
    
    INST_CONFIG_MANAGER = ServerConfigurationManager

    def __init__(self, instance_name, environment="prod", system_folders=True):
        super().__init__("node", instance_name, environment=environment, 
            system_folders=system_folders)
    
    @classmethod
    def from_external_config_file(cls, path, environment="prod", system_folders=True):
        return super().from_external_config_file(
            path, "server", environment, system_folders
        )

    @staticmethod
    def config_exists(instance_name, environment="prod", system_folders=False):
        return AppContext.config_exists("server", 
            instance_name, environment= environment, system_folders=system_folders)
