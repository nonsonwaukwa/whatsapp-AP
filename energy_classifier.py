from enum import Enum
import re
from typing import Dict, List, Tuple

class EnergyLevel(Enum):
    HIGH = "high"
    NEUTRAL = "neutral"
    LOW = "low"
    DISTRESS = "distress"

class EnergyClassifier:
    def __init__(self):
        # Word sets for different energy levels
        self.energy_words: Dict[EnergyLevel, List[str]] = {
            EnergyLevel.HIGH: [
                "pumped", "excited", "ready", "motivated", "energized", "focused",
                "let's go", "feeling great", "on top", "productive", "inspired",
                "crushing it", "energetic", "awesome", "fantastic"
            ],
            EnergyLevel.NEUTRAL: [
                "okay", "fine", "alright", "meh", "not bad", "decent",
                "hanging in", "could be better", "managing", "doing my best",
                "normal", "average"
            ],
            EnergyLevel.LOW: [
                "tired", "exhausted", "drained", "burnt out", "overwhelmed",
                "stressed", "anxious", "struggling", "can't focus", "not feeling",
                "heavy", "unmotivated", "foggy", "no energy", "low energy"
            ],
            EnergyLevel.DISTRESS: [
                "hopeless", "defeated", "stuck", "numb", "can't do anything",
                "what's the point", "done with everything", "just want to sleep",
                "empty", "worthless", "giving up"
            ]
        }

        # Updated response templates to be more empathetic and relatable
        self.responses: Dict[EnergyLevel, List[str]] = {
            EnergyLevel.HIGH: [
                "That's amazing! 🌟 I love those high-energy days too - they're like a superpower, right? Let's make the most of this momentum! Want to see what we can tackle together?",
                "Wow, your energy is contagious! 💫 Those moments when everything feels possible are so precious. I'm here to help you channel that awesome energy - shall we look at your tasks?",
                "Yes! 🚀 I totally get that feeling when your brain is just *on* and ready to go! Let's ride this wave together and see what we can accomplish!"
            ],
            EnergyLevel.NEUTRAL: [
                "Thanks for being honest! 💝 Neutral days are totally valid - sometimes just showing up is a win. Want to break down your tasks into smaller bits? We can take it one step at a time.",
                "I hear you! 🌱 Middle-ground energy can actually be pretty steady for getting things done. No pressure to be at 100% - let's work with what feels manageable today.",
                "Those 'okay' days are so familiar. 🌸 Sometimes they're the best for just steady progress. What feels doable to you right now? We can adjust things as we go."
            ],
            EnergyLevel.LOW: [
                "Hey, I've been there too. 💛 Low energy days are really tough with ADHD/neurodiversity. Let's be super gentle today - maybe we can find just one tiny thing that feels possible? No pressure at all.",
                "I'm giving you a virtual hug (if you want one) 🫂. Executive dysfunction is real and it's not your fault. Would you like to try breaking one small task into micro-steps? I'm right here with you.",
                "Those low-energy days are so hard, and I want you to know you're not alone in this. 💜 Your worth isn't tied to your productivity. Let's find something small and manageable, or just focus on taking care of you today."
            ],
            EnergyLevel.DISTRESS: [
                "I'm right here with you, and I really mean that. 💗 When everything feels impossible, just reaching out is incredibly brave. We can put tasks aside completely - what do you need right now? Even if it's just someone to listen.",
                "Oh friend, I see you and I hear you. 🫂 These moments are so, so hard. Please be extra gentle with yourself - you're dealing with real challenges. Can I help you find some immediate support or comfort?",
                "Your feelings are so valid, and you're not alone in this darkness. 💜 Tasks can absolutely wait - you matter more than any to-do list. Would you like to talk about what's going on, or would you prefer some quiet support?"
            ]
        }

    def classify_energy(self, text: str) -> Tuple[EnergyLevel, float]:
        """
        Classify the energy level from text and return confidence score.
        """
        text = text.lower()
        word_counts = {level: 0 for level in EnergyLevel}
        total_matches = 0

        # Count matches for each energy level
        for level, words in self.energy_words.items():
            for word in words:
                matches = len(re.findall(r'\b' + re.escape(word) + r'\b', text))
                word_counts[level] += matches
                total_matches += matches

        if total_matches == 0:
            return EnergyLevel.NEUTRAL, 0.5

        # If there are any distress signals, prioritize them
        if word_counts[EnergyLevel.DISTRESS] > 0:
            return EnergyLevel.DISTRESS, 1.0

        # Find the energy level with the most matches
        max_count = max(word_counts.values())
        max_levels = [level for level, count in word_counts.items() if count == max_count]

        if len(max_levels) == 1:
            confidence = max_count / total_matches
            return max_levels[0], confidence

        # If there's a tie, prefer the more conservative level
        priority = [EnergyLevel.DISTRESS, EnergyLevel.LOW, EnergyLevel.NEUTRAL, EnergyLevel.HIGH]
        for level in priority:
            if level in max_levels:
                return level, 0.6  # Lower confidence due to mixed signals

    def get_response(self, energy_level: EnergyLevel) -> str:
        """
        Get a random appropriate response for the energy level.
        """
        import random
        return random.choice(self.responses[energy_level])

    def should_modify_tasks(self, energy_level: EnergyLevel) -> bool:
        """
        Determine if tasks should be modified based on energy level.
        """
        return energy_level in [EnergyLevel.LOW, EnergyLevel.DISTRESS]

    def get_task_modification(self, energy_level: EnergyLevel, tasks: List[str]) -> List[str]:
        """
        Modify tasks based on energy level.
        """
        if energy_level == EnergyLevel.HIGH:
            return tasks  # Keep all tasks and maybe suggest adding more
        elif energy_level == EnergyLevel.NEUTRAL:
            return tasks  # Keep regular task list
        elif energy_level == EnergyLevel.LOW:
            # Return only the first task or simplify tasks
            return tasks[:1] if tasks else []
        elif energy_level == EnergyLevel.DISTRESS:
            # Replace tasks with self-care suggestions
            return ["Take care of yourself today. Tasks can wait. 💜"] 