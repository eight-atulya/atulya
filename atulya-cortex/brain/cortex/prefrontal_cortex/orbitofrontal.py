"""
Orbitofrontal Cortex Module
==========================

The orbitofrontal cortex (OFC) implements sophisticated reward processing and
decision evaluation capabilities through integration of sensory, emotional,
and value information.

Key Functions:
    1. Reward Processing
        - Reward evaluation
        - Pleasure computation
        - Satisfaction assessment
        - Motivation calibration
        
    2. Decision Evaluation
        - Outcome prediction
        - Risk assessment
        - Confidence computation
        - Alternative comparison
        
    3. Behavioral Control
        - Response inhibition
        - Impulse control
        - Behavioral adaptation
        - Habit modulation

Technical Implementation:
    Uses specialized neural architectures for:
    - Reward representation
    - Decision evaluation networks
    - Behavioral control systems
    - Prediction optimization
"""

import logging
from typing import Any, Dict, List, Optional, Union
from enum import Enum

from ....utils.neural import NeuralNetwork, RewardNetwork
from ....utils.optimization import DecisionOptimizer
from ....utils.prediction import OutcomePredictor

logger = logging.getLogger(__name__)

class DecisionConfidence(Enum):
    """Confidence levels for decision evaluation"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNCERTAIN = "uncertain"

class RewardType(Enum):
    """Types of reward processing"""
    IMMEDIATE = "immediate"
    DELAYED = "delayed"
    SOCIAL = "social"
    ABSTRACT = "abstract"

class OrbitofrontalPFC:
    """
    Main orbitofrontal cortex implementing reward processing and decision evaluation.
    
    Integrates multiple information streams to optimize decision-making and behavior.
    """
    
    def __init__(self,
                confidence_threshold: float = 0.8,
                reward_discount: float = 0.9):
        """
        Initialize OFC system.

        Args:
            confidence_threshold: Threshold for high confidence decisions
            reward_discount: Temporal discount factor for future rewards
        """
        logger.info("Initializing Orbitofrontal PFC...")
        
        self.confidence_threshold = confidence_threshold
        self.reward_discount = reward_discount
        
        # Initialize processing networks
        self._init_networks()
        
        logger.info("Orbitofrontal PFC initialized successfully")
        
    def _init_networks(self):
        """Initialize neural processing networks"""
        # Reward processing
        self.reward_network = RewardNetwork(
            input_size=256,
            hidden_sizes=[128, 64],
            output_size=32
        )
        
        # Decision evaluation
        self.decision_network = NeuralNetwork(
            input_size=512,
            hidden_sizes=[256, 128],
            output_size=64
        )
        
        # Outcome prediction
        self.predictor = OutcomePredictor(
            prediction_horizon=5
        )
        
        # Optimization
        self.optimizer = DecisionOptimizer()
        
    def optimize_decision(self,
                         executive_input: Dict[str, Any],
                         emotional_input: Dict[str, Any],
                         strategy: Any) -> Dict[str, Any]:
        """
        Optimize decision based on multiple inputs.

        Args:
            executive_input: Input from executive processing
            emotional_input: Input from emotional processing
            strategy: Optimization strategy to use

        Returns:
            Optimized decision output
        """
        # Process reward aspects
        reward_eval = self._process_reward(
            executive_input,
            emotional_input
        )
        
        # Evaluate decision
        decision_eval = self._evaluate_decision(
            executive_input,
            reward_eval
        )
        
        # Predict outcomes
        predictions = self._predict_outcomes(
            decision_eval,
            emotional_input
        )
        
        # Optimize final decision
        optimized = self.optimizer.optimize(
            decision_eval,
            predictions,
            strategy=strategy
        )
        
        return {
            'decision': optimized,
            'confidence': self._compute_confidence(optimized),
            'reward_eval': reward_eval,
            'predictions': predictions
        }
        
    def _process_reward(self,
                       input_data: Dict[str, Any],
                       emotional_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process reward aspects of input.

        Args:
            input_data: Input to process
            emotional_context: Emotional context

        Returns:
            Reward processing results
        """
        # Process through reward network
        reward_output = self.reward_network.process({
            'input': input_data,
            'emotional': emotional_context
        })
        
        # Apply temporal discounting
        for reward_type in RewardType:
            if reward_type.value in reward_output:
                reward_output[reward_type.value] *= self.reward_discount
                
        return reward_output
        
    def _evaluate_decision(self,
                          input_data: Dict[str, Any],
                          reward_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate decision options.

        Args:
            input_data: Input to evaluate
            reward_context: Current reward context

        Returns:
            Decision evaluation results
        """
        return self.decision_network.process({
            'input': input_data,
            'reward': reward_context
        })
        
    def _predict_outcomes(self,
                         decision_eval: Dict[str, Any],
                         emotional_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Predict potential outcomes of decision.

        Args:
            decision_eval: Current decision evaluation
            emotional_context: Emotional context

        Returns:
            Predicted outcomes
        """
        return self.predictor.predict({
            'decision': decision_eval,
            'emotional': emotional_context
        })
        
    def _compute_confidence(self,
                          decision_output: Dict[str, Any]) -> DecisionConfidence:
        """
        Compute confidence in decision.

        Args:
            decision_output: Decision to evaluate

        Returns:
            Confidence level
        """
        confidence_score = decision_output.get('confidence', 0.0)
        
        if confidence_score >= self.confidence_threshold:
            return DecisionConfidence.HIGH
        elif confidence_score >= self.confidence_threshold * 0.7:
            return DecisionConfidence.MEDIUM
        elif confidence_score >= self.confidence_threshold * 0.4:
            return DecisionConfidence.LOW
        else:
            return DecisionConfidence.UNCERTAIN
            
    def select_plan(self,
                   evaluated_plans: List[Dict[str, Any]],
                   strategy: Any) -> Dict[str, Any]:
        """
        Select best plan based on evaluations.

        Args:
            evaluated_plans: List of evaluated plans
            strategy: Selection strategy to use

        Returns:
            Selected plan with evaluations
        """
        # Process all plans
        processed_plans = []
        for plan in evaluated_plans:
            # Optimize decision for each plan
            decision = self.optimize_decision(
                plan['plan'],
                plan['emotional_eval'],
                strategy
            )
            
            processed_plans.append({
                'plan': plan['plan'],
                'evaluation': plan,
                'decision': decision
            })
            
        # Select best plan
        selected = self.optimizer.select_best(
            processed_plans,
            strategy=strategy
        )
        
        return selected