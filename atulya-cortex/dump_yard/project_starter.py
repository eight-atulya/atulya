import os

FILES = [
    # --- brain ---
    "brain/__init__.py",
    "brain/cortex/__init__.py",
    "brain/cortex/sensory_cortex.py",
    "brain/cortex/motor_cortex.py",
    "brain/cortex/association_cortex.py",
    "brain/cortex/prefrontal_cortex.py",
    "brain/cortex/visual_cortex.py",
    "brain/cortex/auditory_cortex.py",
    "brain/cortex/somatosensory_cortex.py",
    
    "brain/limbic_system/__init__.py",
    "brain/limbic_system/amygdala.py",
    "brain/limbic_system/hippocampus.py",
    "brain/limbic_system/hypothalamus.py",
    
    "brain/brainstem/__init__.py",
    "brain/brainstem/medulla_oblongata.py",
    "brain/brainstem/pons.py",
    "brain/brainstem/midbrain.py",
    
    "brain/cerebellum.py",
    "brain/thalamus.py",
    "brain/basal_ganglia.py",
    "brain/corpus_callosum.py",
    "brain/default_mode_network.py",
    "brain/neuroplasticity.py",

    # --- sensors ---
    "sensors/__init__.py",
    "sensors/vision.py",
    "sensors/hearing.py",
    "sensors/touch.py",
    "sensors/smell.py",
    "sensors/taste.py",
    "sensors/proprioception.py",
    "sensors/vestibular.py",
    "sensors/interoception.py",
    "sensors/exteroception.py",

    # --- motors ---
    "motors/__init__.py",
    "motors/movement.py",
    "motors/speech.py",
    "motors/fine_motor_skills.py",
    "motors/facial_expressions.py",
    "motors/autonomic_functions.py",

    # --- communication ---
    "communication/__init__.py",
    "communication/text.py",
    "communication/speech.py",
    "communication/gestures.py",
    "communication/nonverbal.py",
    "communication/haptic_feedback.py",
    "communication/neural_interface.py",

    # --- memory ---
    "memory/__init__.py",
    "memory/short_term_memory.py",
    "memory/long_term_memory.py",
    "memory/working_memory.py",
    "memory/episodic_memory.py",
    "memory/semantic_memory.py",
    "memory/procedural_memory.py",
    "memory/emotional_memory.py",

    # --- learning ---
    "learning/__init__.py",
    "learning/supervised_learning.py",
    "learning/unsupervised_learning.py",
    "learning/reinforcement_learning.py",
    "learning/meta_learning.py",
    "learning/continual_learning.py",
    "learning/transfer_learning.py",

    # --- integration ---
    "integration/__init__.py",
    "integration/sensory_integration.py",
    "integration/motor_integration.py",
    "integration/cognitive_integration.py",
    "integration/emotional_integration.py",

    # --- consciousness ---
    "consciousness/__init__.py",
    "consciousness/self_awareness.py",
    "consciousness/theory_of_mind.py",
    "consciousness/decision_making.py",
    "consciousness/creativity.py",
    "consciousness/dreaming.py",

    # --- tests ---
    "tests/__init__.py",
    "tests/test_brain.py",
    "tests/test_sensors.py",
    "tests/test_motors.py",
    "tests/test_communication.py",
    "tests/test_memory.py",
    "tests/test_learning.py",
    "tests/test_integration.py",
    "tests/test_consciousness.py",

    # --- utils ---
    "utils/__init__.py",
    "utils/logging.py",
    "utils/helpers.py",

    # --- silo ---
    "silo/__init__.py",
    "silo/silo.py",
    "silo/silo_manager.py",
    "silo/silo_client.py",
    "silo/silo_server.py",
    "silo/silo_utils.py",
    "silo/silo_config.py",
    "silo/silo_exceptions.py",
    "silo/silo_logger.py",
    "silo/silo_metrics.py",
    "silo/silo_monitor.py",
    "silo/silo_dashboard.py",
    "silo/silo_visualization.py",
    "silo/silo_data.py",
    "silo/silo_storage.py",
    "silo/silo_analysis.py",
    "silo/silo_simulation.py",

    # --- tools ---
    "tools/__init__.py",
    "tools/toolbox.py",
    "tools/tool_manager.py",
    "tools/tool_client.py",
    "tools/tool_server.py",
    "tools/tool_utils.py",
    "tools/tool_config.py",
    "tools/tool_exceptions.py",
    "tools/tool_logger.py",
    "tools/tool_metrics.py",
    "tools/tool_monitor.py",
    "tools/tool_dashboard.py",
    "tools/tool_visualization.py",
    "tools/tool_data.py",
    "tools/tool_storage.py",
    "tools/tool_analysis.py",
    "tools/tool_simulation.py",

    # --- entanglegement ---
    "entanglement/__init__.py",
    "entanglement/entanglement.py",
    "entanglement/entanglement_manager.py",
    "entanglement/entanglement_client.py",
    "entanglement/entanglement_server.py",
    "entanglement/entanglement_utils.py",
    "entanglement/entanglement_config.py",
    "entanglement/entanglement_exceptions.py",
    "entanglement/entanglement_logger.py",
    "entanglement/entanglement_metrics.py",
    "entanglement/entanglement_monitor.py",
    "entanglement/entanglement_dashboard.py",
    "entanglement/entanglement_visualization.py",
    "entanglement/entanglement_data.py",
    "entanglement/entanglement_storage.py",
    "entanglement/entanglement_analysis.py",
    "entanglement/entanglement_simulation.py",

    # --- quantum ---
    "quantum/__init__.py",
    "quantum/quantum.py",
    "quantum/quantum_manager.py",
    "quantum/quantum_client.py",
    "quantum/quantum_server.py",
    "quantum/quantum_utils.py",
    "quantum/quantum_config.py",
    "quantum/quantum_exceptions.py",
    "quantum/quantum_logger.py",
    "quantum/quantum_metrics.py",
    "quantum/quantum_monitor.py",
    "quantum/quantum_dashboard.py",
    "quantum/quantum_visualization.py",
    "quantum/quantum_data.py",
    "quantum/quantum_storage.py",
    "quantum/quantum_analysis.py",
    "quantum/quantum_simulation.py",

    # --- energy ---
    "energy/__init__.py",
    "energy/energy.py",
    "energy/energy_manager.py",
    "energy/energy_client.py",
    "energy/energy_server.py",
    "energy/energy_utils.py",
    "energy/energy_config.py",
    "energy/energy_exceptions.py",
    "energy/energy_logger.py",
    "energy/energy_metrics.py",
    "energy/energy_monitor.py",
    "energy/energy_dashboard.py",
    "energy/energy_visualization.py",
    "energy/energy_data.py",
    "energy/energy_storage.py",
    "energy/energy_analysis.py",
    "energy/energy_simulation.py",

    # --- blackbox ---
    "blackbox/__init__.py",
    "blackbox/blackbox.py",
    "blackbox/blackbox_manager.py",
    "blackbox/blackbox_client.py",
    "blackbox/blackbox_server.py",
    "blackbox/blackbox_utils.py",
    "blackbox/blackbox_config.py",
    "blackbox/blackbox_exceptions.py",
    "blackbox/blackbox_logger.py",
    "blackbox/blackbox_metrics.py",
    "blackbox/blackbox_monitor.py",
    "blackbox/blackbox_dashboard.py",
    "blackbox/blackbox_visualization.py",
    "blackbox/blackbox_data.py",
    "blackbox/blackbox_storage.py",
    "blackbox/blackbox_analysis.py",
    "blackbox/blackbox_simulation.py",

    # --- bridge ---
    "bridge/__init__.py",
    "bridge/bridge.py",
    "bridge/bridge_manager.py",
    "bridge/bridge_client.py",
    "bridge/bridge_server.py",
    "bridge/bridge_utils.py",
    "bridge/bridge_config.py",
    "bridge/bridge_exceptions.py",
    "bridge/bridge_logger.py",
    "bridge/bridge_metrics.py",
    "bridge/bridge_monitor.py",
    "bridge/bridge_dashboard.py",
    "bridge/bridge_visualization.py",
    "bridge/bridge_data.py",
    "bridge/bridge_storage.py",
    "bridge/bridge_analysis.py",
    "bridge/bridge_simulation.py",

    # --- top-level files ---
    "requirements.txt",
    "setup.py",
    "README.md",
]

def create_project_structure():
    for file_path in FILES:
        dir_name = os.path.dirname(file_path)
        if dir_name:  # Only create a directory if it isn't empty
            os.makedirs(dir_name, exist_ok=True)
        # Create an empty file
        with open(file_path, "w", encoding="utf-8") as f:
            pass

if __name__ == "__main__":
    create_project_structure()
    print("Project structure created successfully!")
