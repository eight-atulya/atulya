"""
Ventromedial Prefrontal Cortex Module
====================================

The ventromedial prefrontal cortex (VMPFC) implements sophisticated emotional
regulation and value-based decision making through integration of cognitive
and emotional information.

Key Functions:
    1. Emotional Regulation
        - Emotion processing
        - Affect modulation
        - Mood stabilization
        - Response control
        
    2. Value Processing
        - Reward evaluation
        - Cost assessment
        - Risk analysis
        - Outcome prediction
        
    3. Social Cognition
        - Social value computation
        - Empathy processing
        - Moral judgment
        - Relationship evaluation

Technical Implementation:
    Uses specialized neural architectures for:
    - Emotion state representation
    - Value computation networks
    - Social context processing
    - Decision optimization
"""

import logging
from typing import Any, Dict, List, Optional, Union
from enum import Enum

from ....utils.neural import NeuralNetwork, EmotionalNetwork
from ....utils.optimization import ValueOptimizer
from ....utils.social import SocialProcessor

logger = logging.getLogger(__name__)

class EmotionalState(Enum):
    """Emotional processing states"""
    NEUTRAL = "neutral"
    REGULATING = "regulating"
    PROCESSING = "processing"
    RESPONDING = "responding"

class ValueStrategy(Enum):
    """Value computation strategies"""
    MAXIMIZE_REWARD = "maximize_reward"
    MINIMIZE_RISK = "minimize_risk"
    BALANCE = "balance"
    SOCIAL_OPTIMAL = "social_optimal"

class VentromedialPFC:
    """
    Main ventromedial prefrontal cortex implementing emotional regulation
    and value-based decision making.
    
    Integrates emotional and cognitive information for adaptive behavior.
    """
    
    def __init__(self,
                default_strategy: ValueStrategy = ValueStrategy.BALANCE,
                emotion_threshold: float = 0.7):
        """
        Initialize VMPFC system.

        Args:
            default_strategy: Default value computation strategy
            emotion_threshold: Threshold for emotion regulation
        """
        logger.info("Initializing Ventromedial PFC...")
        
        self.default_strategy = default_strategy
        self.emotion_threshold = emotion_threshold
        
        # Initialize processing networks
        self._init_networks()
        
        self.emotional_state = EmotionalState.NEUTRAL
        
        logger.info("Ventromedial PFC initialized successfully")
        
    def _init_networks(self):
        """Initialize neural processing networks"""
        # Emotional processing
        self.emotion_network = EmotionalNetwork(
            input_size=512,
            hidden_sizes=[256, 128],
            output_size=64
        )
        
        # Value computation
        self.value_network = NeuralNetwork(
            input_size=256,
            hidden_sizes=[128, 64],
            output_size=32
        )
        
        # Social processing
        self.social_processor = SocialProcessor(
            embedding_size=128
        )
        
        # Optimization
        self.value_optimizer = ValueOptimizer()
        
    def evaluate(self,
                executive_input: Dict[str, Any],
                memory_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate input through emotional and value processing.

        Args:
            executive_input: Input from executive processing
            memory_context: Relevant memory context

        Returns:
            Emotional and value evaluation results
        """
        # Process emotional content
        emotional_result = self._process_emotions(
            executive_input,
            memory_context
        )
        
        # Compute values
        value_result = self._compute_values(
            executive_input,
            emotional_result
        )
        
        # Social processing
        social_result = self._process_social(
            executive_input,
            emotional_result,
            memory_context
        )
        
        return {
            'emotional': emotional_result,
            'value': value_result,
            'social': social_result
        }
        
    def _process_emotions(self,
                         input_data: Dict[str, Any],
                         context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process emotional aspects of input.

        Args:
            input_data: Input to process
            context: Processing context

        Returns:
            Emotional processing results
        """
        self.emotional_state = EmotionalState.PROCESSING
        
        # Process through emotion network
        emotion_output = self.emotion_network.process(
            input_data,
            context
        )
        
        # Check for regulation needs
        if emotion_output['intensity'] > self.emotion_threshold:
            self.emotional_state = EmotionalState.REGULATING
            emotion_output = self._regulate_emotions(emotion_output)
            
        self.emotional_state = EmotionalState.NEUTRAL
        return emotion_output
        
    def _compute_values(self,
                       input_data: Dict[str, Any],
                       emotional_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compute values for decision making.

        Args:
            input_data: Input to evaluate
            emotional_context: Current emotional context

        Returns:
            Value computation results
        """
        # Process through value network
        value_output = self.value_network.process({
            'input': input_data,
            'emotional': emotional_context
        })
        
        # Optimize values
        optimized = self.value_optimizer.optimize(
            value_output,
            strategy=self.default_strategy
        )
        
        return optimized
        
    def _process_social(self,
                       input_data: Dict[str, Any],
                       emotional_result: Dict[str, Any],
                       memory_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process social aspects of input.

        Args:
            input_data: Input to process
            emotional_result: Current emotional processing
            memory_context: Memory context

        Returns:
            Social processing results
        """
        return self.social_processor.process({
            'input': input_data,
            'emotional': emotional_result,
            'memory': memory_context
        })
        
    def _regulate_emotions(self, emotion_output: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply emotional regulation.

        Args:
            emotion_output: Emotional state to regulate

        Returns:
            Regulated emotional state
        """
        regulated = self.emotion_network.regulate(
            emotion_output,
            target_intensity=self.emotion_threshold
        )
        return regulated
        
    def evaluate_plans(self,
                      plans: List[Dict[str, Any]],
                      emotional_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Evaluate plans considering emotional context.

        Args:
            plans: Plans to evaluate
            emotional_context: Current emotional context

        Returns:
            Evaluated plans with emotional/value scores
        """
        evaluated_plans = []
        for plan in plans:
            # Emotional evaluation
            emotional_eval = self._process_emotions(
                plan,
                emotional_context
            )
            
            # Value computation
            value_eval = self._compute_values(
                plan,
                emotional_eval
            )
            
            # Combine evaluations
            evaluated_plans.append({
                'plan': plan,
                'emotional_eval': emotional_eval,
                'value_eval': value_eval
            })
            
        return evaluated_plans