
DEFAULT_CARDS_PER_STACK = 8

# TODO(kamens): this will probably be persisted to the datastore in the form of a double-pickled 
# list of cards attached to UserTopics or something of the sort.
class Card(object):
    """ Holds single Card's state.
    Subclassed by ProblemCard and, in the future, stuff like VideoCard, SurveyCard, etc.
    """

    def __init__(self):
        self.card_type = "unknown"
        self.leaves_available = 5
        self.leaves_earned = 0
        self.done = False

class EndOfStackCard(Card):
    """ Single Card at end of a stack that shows all sorts of useful end-of-stack info. """

    def __init__(self):
        Card.__init__(self)

        self.card_type = "endofstack"

class ProblemCard(Card):
    """ Holds single Card's state specific to exercise problems. """

    def __init__(self, exercise_name):
        Card.__init__(self)

        self.card_type = "problem"
        self.exercise_name = exercise_name

def append_end_of_stack(stack):
    return stack + [EndOfStackCard()]

# TODO(kamens): this will eventually be able to handle multiple exercises, 
# topics, and probably eventually return other types of cards.
def get_problem_stack(exercise):
    return append_end_of_stack([ProblemCard(exercise.name) for i in range(DEFAULT_CARDS_PER_STACK)])
