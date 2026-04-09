import os
import sys
import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv
from stable_baselines3.common.callbacks import EvalCallback

MODEL_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(MODEL_DIR, "data")

class NiftyTradingEnv(gym.Env):
    """
    Custom Gymnasium Environment for Nifty Trading.
    Instead of predicting UP/DOWN (Accuracy), the model takes actions to maximize Profit (Reward).
    """
    metadata = {'render_modes': ['human']}

    def __init__(self, data_file="nifty_15m.csv", mode="train"):
        super(NiftyTradingEnv, self).__init__()
        
        # Load and prep data
        self.df = pd.read_csv(os.path.join(DATA_DIR, data_file), index_col=0, parse_dates=True)
        # Note: Add the 31 features here via feature_builder logic in reality
        self.prices = self.df['Close'].values
        self.highs = self.df['High'].values
        self.lows = self.df['Low'].values
        
        # We need continuous features
        from train_multitf import add_features, FEATURE_COLUMNS
        self.df = add_features(self.df).dropna(subset=FEATURE_COLUMNS)
        self.features = self.df[FEATURE_COLUMNS].values
        self.prices = self.df['Close'].values
        
        # Split train/test
        split = int(len(self.df) * 0.8)
        if mode == "train":
            self.features = self.features[:split]
            self.prices = self.prices[:split]
        else:
            self.features = self.features[split:]
            self.prices = self.prices[split:]

        # Actions: 0 = Hold/Cash, 1 = Buy CE, 2 = Buy PE
        self.action_space = spaces.Discrete(3)
        
        # Observations: 31 features + current portfolio state
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(len(FEATURE_COLUMNS) + 2,), dtype=np.float32
        )
        
        self.initial_balance = 100000
        self.balance = self.initial_balance
        self.current_step = 0
        self.position = 0          # 0 = none, 1 = CE, 2 = PE
        self.entry_price = 0.0

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.balance = self.initial_balance
        self.current_step = 0
        self.position = 0
        self.entry_price = 0.0
        return self._get_obs(), {}

    def _get_obs(self):
        # Current market features + our position status + unrealized profit
        market_feat = self.features[self.current_step]
        unrealized = 0.0
        if self.position == 1:
            unrealized = self.prices[self.current_step] - self.entry_price
        elif self.position == 2:
            unrealized = self.entry_price - self.prices[self.current_step]
            
        pos_arr = np.array([self.position, unrealized], dtype=np.float32)
        return np.concatenate([market_feat, pos_arr])

    def step(self, action):
        done = False
        reward = 0.0
        
        current_price = self.prices[self.current_step]
        
        # Logic: If holding a position, track its value
        if self.position == 1: # Long CE
            reward = current_price - self.prices[self.current_step - 1]
        elif self.position == 2: # Long PE
            reward = self.prices[self.current_step - 1] - current_price

        # Action handling
        if action == 1 and self.position != 1:  # Switch to CE
            self.position = 1
            self.entry_price = current_price
            reward -= 2.0 # Slippage / Brokerage penalty
        elif action == 2 and self.position != 2: # Switch to PE
            self.position = 2
            self.entry_price = current_price
            reward -= 2.0 # Slippage penalty
        elif action == 0 and self.position != 0: # Square off
            self.position = 0
            reward -= 1.0
            
        self.balance += reward
        self.current_step += 1

        if self.current_step >= len(self.prices) - 1:
            done = True
            
        # Give immense penalty for going broke
        if self.balance < self.initial_balance * 0.5:
            done = True
            reward = -100

        return self._get_obs(), float(reward), done, False, {}

def train_rl():
    print("Initializing RL Gym Environment for Nifty...")
    env = DummyVecEnv([lambda: NiftyTradingEnv("nifty_15m.csv", mode="train")])
    eval_env = DummyVecEnv([lambda: NiftyTradingEnv("nifty_15m.csv", mode="test")])
    
    # Eval callback to save best model during training
    eval_callback = EvalCallback(eval_env, best_model_save_path=MODEL_DIR,
                                 log_path=os.path.join(MODEL_DIR, "logs"), eval_freq=5000)

    # Use PPO (Proximal Policy Optimization) - arguably best for finance
    print("Building PPO Agent (actor-critic architecture)...")
    model = PPO("MlpPolicy", env, verbose=1, learning_rate=0.0005, n_steps=2048, batch_size=128, ent_coef=0.01)
    
    print("Training Agent (Will take thousands of timesteps to learn patterns)...")
    model.learn(total_timesteps=100000, callback=eval_callback)
    
    model_path = os.path.join(MODEL_DIR, "nifty_ppo_agent")
    model.save(model_path)
    print(f"RL Agent saved to {model_path}.zip")

if __name__ == "__main__":
    train_rl()
