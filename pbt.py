"""
An implementation of population-based training of neural networks for
TensorFlow.
"""

from typing import Iterable, List, Callable, TypeVar, Generic
from collections import OrderedDict
import tensorflow as tf

T = TypeVar('T', bound='Graph')


class Graph:
    """
    A TensorFlow graph that a Cluster can train.

    A Graph need not have a TensorFlow Graph object all to itself.

    A Graph has an associated TensorFlow Session that it uses to run its
    Operations and Variables.
    """

    sess: tf.Session

    def __init__(self, sess: tf.Session) -> None:
        """
        Creates a new Graph with associated Session <sess>.
        """
        self.sess = sess

    def initialize_variables(self) -> None:
        """
        Runs the initializer Operations of all of the TensorFlow Variables that
        this Graph created in its initializer.
        """
        raise NotImplementedError

    def get_metric(self) -> float:
        """
        Returns a metric for this Graph, typically its accuracy, that
        represents its effectiveness at its task and allows it to be compared
        to other Graphs with the same task.
        """
        raise NotImplementedError

    def get_step_num(self) -> int:
        """
        Returns the number of training steps that this Graph has performed.
        """
        raise NotImplementedError

    def train(self) -> None:
        """
        Trains this Graph until it is ready to consider exploitation of its
        population.
        """
        raise NotImplementedError

    def exploit_and_or_explore(self, population: List['Graph']) -> None:
        """
        Exploits <population>, a list of Graphs of the same type as this one,
        to improve this Graph, and/or modifies this Graph to explore a
        different option, if those actions are judged to be currently
        necessary.
        """
        raise NotImplementedError

    @staticmethod
    def population_exploit_explore(population: List['Graph']) -> None:
        """
        Causes all of the Graphs in <population>, a list of Graphs of this
        type, to exploit and/or explore each other simultaneously, like a
        combined version of all of the Graphs' exploit_and_or_explore()
        methods.
        """
        raise NotImplementedError


class Cluster(Generic[T]):
    """
    A system that can perform population-based training of Graphs.

    Any TensorFlow Variables created in the initializers of a Cluster's
    Graphs should be initialized by calling the Cluster's
    initialize_variables() method. Even if such variables are global, they may
    not be on the proper device to be initialized if a Session is instructed
    to initialize all global variables.

    T is the type of Graph that this Cluster trains.
    """

    def get_population(self) -> List[T]:
        """
        Returns this Cluster's population of Graphs.

        The returned list should not be modified.
        """
        raise NotImplementedError

    def initialize_variables(self) -> None:
        """
        Initializes all of the TensorFlow Variables that this Cluster's Graphs
        created in their initializers.
        """
        raise NotImplementedError

    def get_highest_metric_graph(self) -> T:
        """
        Returns this Cluster's Graph with the highest metric.
        """
        raise NotImplementedError

    def train(self, training_cond: Callable[[T, List[T]], bool]) -> None:
        """
        Performs population-based training on this Cluster's population.

        <training_cond> is a Callable that, when passed a Graph and this
        Cluster's population, returns whether the training of the specified
        Graph should continue.
        """
        raise NotImplementedError


class LocalCluster(Generic[T], Cluster[T]):
    """
    A Cluster that simulates synchronous training with a single local thread.
    """

    sess: tf.Session
    population: List[T]

    def __init__(self, pop_size: int, graph_maker: Callable[[tf.Session], T]) -> None:
        """
        Creates a new LocalCluster with <pop_size> graphs returned by
        <graph_maker> as its population.

        <pop_size> is the number of Graphs that will make up this
        LocalCluster's population. <graph_maker> is a Callable that returns a
        new T with the specified Session each time it is called.
        """
        self.sess = tf.Session()
        self.population = [graph_maker(self.sess) for _ in range(pop_size)]

    def get_population(self) -> List[T]:
        return self.population

    def initialize_variables(self):
        for graph in self.population:
            graph.initialize_variables()

    def get_highest_metric_graph(self) -> T:
        highest_graph = None
        highest_metric = None
        for graph in self.population:
            if highest_graph is None:
                highest_graph = graph
                highest_metric = graph.get_metric()
            else:
                metric = graph.get_metric()
                if metric > highest_metric:
                    highest_graph = graph
                    highest_metric = metric
        return highest_graph

    def train(self, training_cond: Callable[[T, List[T]], bool]) -> None:
        while True:
            keep_training = False
            for graph in self.population:
                if training_cond(graph, self.population):
                    keep_training = True
                    graph.train()
            if keep_training:
                for graph in self.population:
                    if training_cond(graph, self.population):
                        graph.population_exploit_explore(self.population)
                        break
                else:
                    break
            else:
                break


class Hyperparameter:
    """
    A non-trained parameter of a HyperparamsGraph.

    A Hyperparameter's __str__() method should return a string representing its
    value.

    A Hyperparameter may be declared unused, in which case new
    HyperparamsUpdates will not record it.
    """

    name: str
    graph: 'HyperparamsGraph'
    unused: bool

    def __init__(self, name: str, graph: 'HyperparamsGraph', unused: bool) -> None:
        """
        Creates a new Hyperparameter of <graph> with descriptive name <name>
        and initial unused status <unused>.
        """
        self.name = name
        self.graph = graph
        self.unused = unused
        graph.hyperparams.append(self)

    def initialize_variables(self) -> None:
        """
        Runs the initializer Operations of all of the TensorFlow Variables that
        this Hyperparameter created in its initializer.
        """
        raise NotImplementedError

    def copy(self, hyperparam: 'Hyperparameter') -> None:
        """
        Sets this Hyperparameter's value to that of <hyperparam>, a
        Hyperparameter of the same type.
        """
        raise NotImplementedError

    def perturb(self) -> None:
        """
        Alters this Hyperparameter to explore a different option for it.
        """
        raise NotImplementedError

    def resample(self) -> None:
        """
        Resets this Hyperparameter's value, re-randomizing any random choices
        that determined it.
        """
        raise NotImplementedError


class HyperparamsUpdate:
    """
    Stores information about a HyperparamsGraph's update of its
    hyperparameters.
    """

    prev: 'HyperparamsUpdate'
    step_num: int
    hyperparams: OrderedDict

    def __init__(self, graph: 'HyperparamsGraph') -> None:
        """
        Creates a new HyperparamsUpdate that stores <graph>'s current
        information.
        """
        self.prev = graph.last_update
        self.step_num = graph.get_step_num()
        self.hyperparams = OrderedDict()
        for hyperparam in graph.hyperparams:
            if not hyperparam.unused:
                self.hyperparams[hyperparam.name] = str(hyperparam)


class HyperparamsGraph(Graph):
    """
    A Graph that stores its hyperparameters as a list of Hyperparameters.
    """

    hyperparams: List[Hyperparameter]
    last_update: HyperparamsUpdate

    def __init__(self, sess: tf.Session) -> None:
        """
        Creates a new HyperparamsGraph with associated Session <sess>.
        """
        super().__init__(sess)
        self.hyperparams = []
        self.last_update = None

    def initialize_variables(self) -> None:
        for hyperparam in self.hyperparams:
            hyperparam.initialize_variables()
        self.record_update()

    def record_update(self) -> None:
        """
        Records this HyperparamsGraph's current information as a new update to
        its hyperparameters.
        """
        self.last_update = HyperparamsUpdate(self)

    def get_update_history(self) -> Iterable[HyperparamsUpdate]:
        """
        Returns an iterable of this HyperparamsGraph's HyperparamsUpdates in
        order from least to most recent.
        """
        updates = []
        update = self.last_update
        while update is not None:
            updates.append(update)
            update = update.prev
        return reversed(updates)

    def print_update_history(self) -> None:
        """
        Prints this HyperparamsGraph's hyperparameter update history to the
        console.
        """
        updates = []
        update = self.last_update
        while update is not None:
            updates.append(update)
            update = update.prev
        while len(updates) > 0:
            update = updates.pop()
            print('Step', update.step_num)
            for name, value in update.hyperparams.items():
                print(name + ': ' + value)
            print()
