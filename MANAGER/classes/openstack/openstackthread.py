import logging

logger = logging.getLogger(__name__)

import threading
import time
from typing import Optional, Callable
from .auth import OpenstackAuth
from .info import OpenstackInfo
from .creation import OpenstackCreation
from .deletion import OpenstackDeletion
from .openstackerrors import OpenstackCreationMissingKey, OpenstackResourceNotFound, OpenstackVMStateChanged, OpenstackMissingArgument, OpenstackDeletionMissingVM
from .info.data import VM, Host, Flavor, Keypair, Network, Image, Security
###################################
#      OpenStack Thread           #
###################################

class OpenstackThread(threading.Thread):

    def __init__(self, **kwargs):
        super().__init__(name="OpenStack_Thread", daemon=True)
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._data_lock = threading.Lock()
        
        # --- Loop ---
        self.refresh_time = kwargs["refresh_time"]      
        self.creation_variables = kwargs["creation_variables"]   
        
        # --- Data by ID ---
        self.dict_vms        : dict[str, VM]       = {} # ID
        self.dict_hosts      : dict[str, Host]     = {} # ID
        self.dict_images     : dict[str, Image]    = {} # ID
        self.dict_flavors    : dict[str, Flavor]   = {} # ID
        self.dict_networks   : dict[str, Network]  = {} # ID
        self.dict_keypairs   : dict[str, Keypair]  = {} # NAME
        self.dict_securities : dict[str, Security] = {} # NAME -> Creation VMS ( id was avaliable but not accepted )
        
        # --- Authenticate ---
        self.auth = OpenstackAuth(**kwargs)
        if not self.auth.authenticate():
            raise BrokenPipeError("[OpenstackThread] Authentication failed")
        
        # --- Handlers ---
        self.openstack_info = OpenstackInfo(self.auth, kwargs.get('info_endpoints', {}))
        self.openstack_creation = OpenstackCreation(self.auth, kwargs.get('creation_timeout'), kwargs.get('creation_endpoint'))
        self.openstack_deletion = OpenstackDeletion(self.auth, kwargs.get('deletion_timeout'), kwargs.get('deletion_endpoint'))
        
        # --- WebSocket (set by ClientManager) ---
        self.websocket: Optional[Callable[[dict], bool]] = None
        
    def start(self):
        """ Scan containers after init """
        self.load()
        self._ready_event.set()  # Signal that initial load is complete
        super().start()
    
    def wait_until_ready(self, timeout=30):
        """Wait for initial load to complete"""
        return self._ready_event.wait(timeout)

    def stop(self) -> None:
        logger.info("[OpenstackThread] Stopping...")
        self._stop_event.set()

    def run(self):
        logger.info("[OpenstackThread] Started")
        
        while not self._stop_event.is_set():
            try:
                # --- Token ---
                self.auth.check_and_refresh_token()
                self.load()
                time.sleep(self.refresh_time)
                
            except Exception as e:
                logger.info(" OpenstackThread main loop: {e}")
        
        logger.info("[OpenstackThread] Stopped")
        
    def _send_alert(self, error: Exception):
        if self.websocket:
            try:
                alert_payload = {
                    "type": "alert",
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "timestamp": time.time()
                }
                self.websocket(alert_payload)
            except Exception as e:
                logger.info(" Failed to send alert: {e}")
    
    def load(self) -> None:
        # Fetch all data outside the lock to avoid holding it during slow API calls
        new_vms        = self.openstack_info.load_vms()
        #new_hosts     = self.openstack_info.load_hosts()  # No permission :(
        new_images     = self.openstack_info.load_images()
        new_flavors    = self.openstack_info.load_flavors()
        new_networks   = self.openstack_info.load_networks()
        new_keypairs   = self.openstack_info.load_keypairs()
        new_securities = self.openstack_info.load_security()

        # Detect VM state changes before swapping (compare against current dict_vms)
        vm_changes = []
        for vm_id, new_vm in new_vms.items():
            if vm_id in self.dict_vms:
                has_changed, changed_fields = new_vm.has_changed(self.dict_vms[vm_id])
                if has_changed:
                    vm_changes.append(OpenstackVMStateChanged(vm_id, new_vm.name, changed_fields))

        # Atomically swap all dicts in a single lock acquisition
        with self._data_lock:
            self.dict_vms        = new_vms
            self.dict_images     = new_images
            self.dict_flavors    = new_flavors
            self.dict_networks   = new_networks
            self.dict_keypairs   = new_keypairs
            self.dict_securities = new_securities

        # Send alerts outside the lock
        for error in vm_changes:
            self._send_alert(error)
    
    
    # -------------------- CHECKS --------------------
    def create_vm(self, data: dict) -> str:
        
        # --- Needed ---
        for variable in self.creation_variables:
            if variable not in data:
                raise OpenstackCreationMissingKey(variable)

        # --- Not found ---
        with self._data_lock:
            if data["keypair"]    not in self.dict_keypairs:   raise OpenstackResourceNotFound("keypair", data["keypair"])
            if data["image_id"]   not in self.dict_images:     raise OpenstackResourceNotFound("image_id", data["image_id"])
            if data["security"]   not in self.dict_securities: raise OpenstackResourceNotFound("security", data["security"])
            if data["flavor_id"]  not in self.dict_flavors:    raise OpenstackResourceNotFound("flavor_id", data["flavor_id"])
            if data["network_id"] not in self.dict_networks:   raise OpenstackResourceNotFound("network_id", data["network_id"])
        
        # --- Dunno ---
        if "config_drive" not in data:
            data["config_drive"] = False
        
        # --- Request ---
        vm_ip, vm_id = self.openstack_creation.handle(**data)
        
        # --- Update dict immediately on success ---
        if vm_ip and vm_id:
            vm = self.openstack_info.load_single_vm(vm_id)
            with self._data_lock:
                self.dict_vms[vm_id] = vm
        
        return vm_ip, vm_id
    
    def delete_vm(self, data: dict) -> bool:
        
        # --- Check ---
        if not "vm_id" in data: raise OpenstackMissingArgument("vm_id")
        vm_id = data["vm_id"]

        # --- Exist ---
        with self._data_lock:
            if vm_id not in self.dict_vms:
                raise OpenstackDeletionMissingVM(vm_id)
        
        # --- Request ---
        self.openstack_deletion.handle(vm_id)
        
        # --- Remove ---
        with self._data_lock:
            self.dict_vms.pop(vm_id, None)
        
        logger.info(" Deregistered {vm_id}")
        return data
