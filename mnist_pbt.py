"""
A convolutional neural network for MNIST that is compatible with
population-based training.
"""

from typing import Any, Iterable, List, Tuple, Callable
import math
import random
import os
from matplotlib.axes import Axes
from matplotlib.lines import Line2D
import matplotlib.pyplot as plt
import tensorflow as tf
from pbt import Hyperparameter, HyperparamsUpdate, HyperparamsGraph
from mnist import ConvNet as MNISTConvNet, MNIST_TRAIN_SIZE, MNIST_TEST_SIZE, MNIST_TEST_BATCH_SIZE,\
    get_mnist_data


class FloatHyperparameter(Hyperparameter):
    """
    A type of Hyperparameter with a single floating-point value.
    """

    value_setter: Callable[[], float]
    value: tf.Variable
    factor: float
    min_value: float
    max_value: float

    def _limited(self, value: float) -> float:
        if self.min_value is not None:
            value = max(value, self.min_value)
        if self.max_value is not None:
            value = min(value, self.max_value)
        return value

    def __init__(self, name: str, graph: HyperparamsGraph, unused: bool,
                 value_setter: Callable[[], float], factor: float,
                 min_value: float, max_value: float) -> None:
        """
        Creates a new FloatHyperparameter of graph <graph> with descriptive
        name <name> and initial unused status <unused>.

        <value_setter> is a Callable that samples and returns an initial value.
        <factor> is the factor by which the value will be randomly multiplied
        or divided when perturbed. <min_value> is the minimum possible value,
        or None if there should be none. <max_value> is the maximum possible
        value, or None if there should be none.
        """
        super().__init__(name, graph, unused)
        self.value_setter = value_setter
        self.factor = factor
        self.min_value = min_value
        self.max_value = max_value
        self.value = tf.Variable(self._limited(value_setter()), trainable=False)

    def __str__(self) -> str:
        return str(self.get_value())

    def initialize_variables(self) -> None:
        self.graph.sess.run(self.value.initializer)

    def get_value(self) -> float:
        return self.graph.sess.run(self.value)

    def set_value(self, value: float) -> None:
        self.value.load(value, self.graph.sess)

    def perturb(self) -> None:
        value = self.get_value()
        if random.random() < 0.5:
            value *= self.factor
        else:
            value /= self.factor
        self.set_value(self._limited(value))

    def resample(self) -> None:
        self.set_value(self._limited(self.value_setter()))


class OptimizerInfo:
    """
    Stores a TensorFlow Optimizer and information about it.
    """

    optimizer: tf.train.Optimizer
    minimizer: tf.Operation
    vars: List[tf.Variable]
    hyperparams: List[Hyperparameter]

    def __init__(self, optimizer: tf.train.Optimizer,
                 to_minimize, hyperparams: List[Hyperparameter]) -> None:
        """
        Creates a new OptimizerInfo for <optimizer>.

        <to_minimize> is a TensorFlow Tensor that <optimizer> should be used to
        minimize, and <hyperparams> is a list of all of the Hyperparameters
        that affect <optimizer>'s behavior.
        """
        self.optimizer = optimizer
        self.minimizer = optimizer.minimize(to_minimize)
        self.vars = optimizer.variables()
        self.hyperparams = hyperparams


class OptimizerHyperparameter(Hyperparameter):
    """
    A Hyperparameter whose value is one of several TensorFlow Optimizers.
    """

    opt_info: List[OptimizerInfo]
    opt_index: int
    vary_opt: bool

    def _set_sub_hyperparams_unused(self, unused: bool) -> None:
        for hyperparam in self.opt_info[self.opt_index].hyperparams:
            hyperparam.unused = unused

    def __init__(self, graph: HyperparamsGraph, to_minimize, vary_opt: bool) -> None:
        """
        Creates a new OptimizerHyperparameter of <graph> with Optimizers that
        can be used to minimize the TensorFlow Tensor <to_minimize>.

        If <vary_opt> is True, the Optimizer used will be sampled at random and
        can be perturbed. Otherwise, it will always be an AdamOptimizer.
        """
        super().__init__('Optimizer', graph, False)
        self.opt_info = []
        learning_rate = FloatHyperparameter('Learning rate', self.graph, True,
                                            lambda: 10 ** random.uniform(-6, 0), 1.2, 10 ** -6, 1)
        # GradientDescentOptimizer
        optimizer = tf.train.GradientDescentOptimizer(learning_rate.value)
        self.opt_info.append(OptimizerInfo(optimizer, to_minimize, [learning_rate]))
        # AdagradOptimizer
        optimizer = tf.train.AdagradOptimizer(learning_rate.value, 0.01)
        self.opt_info.append(OptimizerInfo(optimizer, to_minimize, [learning_rate]))
        # MomentumOptimizer
        momentum = FloatHyperparameter('Momentum', self.graph, True,
                                       lambda: random.uniform(0, 1), 1.2, 0, 1)
        optimizer = tf.train.MomentumOptimizer(learning_rate.value, momentum.value)
        self.opt_info.append(OptimizerInfo(optimizer, to_minimize, [learning_rate, momentum]))
        # AdamOptimizer
        optimizer = tf.train.AdamOptimizer(learning_rate.value)
        self.opt_info.append(OptimizerInfo(optimizer, to_minimize, [learning_rate]))
        if vary_opt:
            self.opt_index = random.randrange(len(self.opt_info))
        else:
            self.opt_index = 3
        self._set_sub_hyperparams_unused(False)
        self.vary_opt = vary_opt

    def __str__(self) -> str:
        return self.opt_info[self.opt_index].optimizer.__class__.__name__

    def initialize_variables(self) -> None:
        self.graph.sess.run([var.initializer for info in self.opt_info for var in info.vars])

    def get_value(self):
        return (self.opt_index, self.graph.sess.run(self.opt_info[self.opt_index].vars), self.vary_opt)

    def set_value(self, value) -> None:
        opt_index, var_values, vary_opt = value
        self._set_sub_hyperparams_unused(True)
        self.opt_index = opt_index
        vars = self.opt_info[opt_index].vars
        for i in range(len(vars)):
            vars[i].load(var_values[i], self.graph.sess)
        self._set_sub_hyperparams_unused(False)
        self.vary_opt = vary_opt

    def _switch_to_opt(self, opt_index: int):
        self._set_sub_hyperparams_unused(True)
        self.opt_index = opt_index
        info = self.opt_info[self.opt_index]
        self.graph.sess.run([var.initializer for var in info.vars])
        for hyperparam in info.hyperparams:
            hyperparam.resample()
            hyperparam.unused = False

    def perturb(self) -> None:
        if self.vary_opt:
            num_opts = len(self.opt_info)
            if num_opts >= 2:
                self._switch_to_opt((self.opt_index + random.randrange(1, num_opts)) % num_opts)

    def resample(self) -> None:
        if self.vary_opt:
            self._switch_to_opt(random.randrange(len(self.opt_info)))

    def get_current_minimizer(self) -> tf.Operation:
        """
        Returns a TensorFlow Operation that uses this OptimizerHyperparameter's
        current Optimizer to minimize the Tensor specified in its initializer.
        """
        return self.opt_info[self.opt_index].minimizer


class ConvNet(HyperparamsGraph):
    """
    A PBT-compatible version of an MNIST convnet that trains itself to minimize
    cross entropy.
    """

    train_next: Any
    test_next: Any
    net: MNISTConvNet
    optimizer: OptimizerHyperparameter
    keep_prob: FloatHyperparameter
    accuracy: float

    def __init__(self, num: int, sess: tf.Session, vary_opt: bool) -> None:
        """
        Creates a new ConvNet, numbered <num> in its population, with
        associated Session <sess>.

        If <vary_opt> is True, the TensorFlow Optimizer used will be sampled at
        random and can be perturbed. Otherwise, it will always be an
        AdamOptimizer.

        This method uses mnist.get_mnist_data() to obtain this ConvNet's
        training and testing data. Thus, mnist.set_mnist_data() must be called
        before any ConvNets are initialized.
        """
        super().__init__(num, sess)
        train_data, test_data = get_mnist_data()
        self.train_next = train_data\
            .shuffle(MNIST_TRAIN_SIZE).batch(50).repeat().make_one_shot_iterator().get_next()
        self.test_iterator = test_data.batch(MNIST_TEST_BATCH_SIZE).make_initializable_iterator()
        self.test_next = self.test_iterator.get_next()
        self.x = tf.placeholder(tf.float32, [None, 784])
        self.y_ = tf.placeholder(tf.int32, [None])
        one_hot_y_ = tf.one_hot(self.y_, 10)
        self.keep_prob = FloatHyperparameter('Keep probability', self, False,
                                             lambda: random.uniform(0.1, 1), 1.2, 0.1, 1)
        self.net = MNISTConvNet(sess, self.x, one_hot_y_, self.keep_prob.value)
        cross_entropy = tf.reduce_mean(
            tf.nn.softmax_cross_entropy_with_logits_v2(labels=one_hot_y_, logits=self.net.y))
        self.optimizer = OptimizerHyperparameter(self, cross_entropy, vary_opt)
        self.accuracy = None
        self.value = None

    def initialize_variables(self) -> None:
        super().initialize_variables()
        self.net.initialize_variables()

    def get_value(self):
        if self.value is None:
            self.value = (self.step_num, self.sess.run(self.net.vars),
                          [hyperparam.get_value() for hyperparam in self.hyperparams],
                          self.last_update, self.accuracy)
        return self.value

    def set_value(self, value) -> None:
        step_num, var_values, hyperparam_values, last_update, accuracy = value
        self.step_num = step_num
        for i in range(len(self.net.vars)):
            self.net.vars[i].load(var_values[i], self.sess)
        for i in range(len(self.hyperparams)):
            self.hyperparams[i].set_value(hyperparam_values[i])
        self.last_update = last_update
        self.accuracy = accuracy
        self.value = value

    def get_accuracy(self) -> float:
        """
        Returns this ConvNet's accuracy score on its testing Dataset.
        """
        if self.accuracy is None:
            self.sess.run(self.test_iterator.initializer)
            size_accuracy = 0
            try:
                while True:
                    test_images, test_labels = self.sess.run(self.test_next)
                    batch_size = test_images.shape[0]
                    batch_accuracy = self.sess.run(self.net.accuracy,
                                                   feed_dict={self.x: test_images, self.y_: test_labels,
                                                              self.keep_prob.value: 1})
                    size_accuracy += batch_size * batch_accuracy
            except tf.errors.OutOfRangeError:
                pass
            self.accuracy = size_accuracy / MNIST_TEST_SIZE
            self.value = None
        return self.accuracy

    def get_metric(self) -> float:
        return self.get_accuracy()

    def _train_step(self) -> None:
        train_images, train_labels = self.sess.run(self.train_next)
        self.sess.run(self.optimizer.get_current_minimizer(),
                      feed_dict={self.x: train_images, self.y_: train_labels})
        self.accuracy = None
        self.value = None
        self.step_num += 1

    def train(self) -> None:
        while True:
            self._train_step()
            if self.step_num % 500 == 0:
                break

    def explore(self):
        """
        Randomly perturbs some of this ConvNet's hyperparameters.
        """
        # Ensure that at least one used hyperparameter is perturbed
        rand = random.randrange(1, 2 ** sum(1 for hyperparam in self.hyperparams if not hyperparam.unused))
        perturbed_used_hyperparam = False
        for i in range(len(self.hyperparams)):
            hyperparam = self.hyperparams[i]
            if perturbed_used_hyperparam or hyperparam.unused:
                if random.random() < 0.5:
                    hyperparam.perturb()
            elif rand & (2 ** i) != 0:
                hyperparam.perturb()
                perturbed_used_hyperparam = True
        self.value = None
        self.record_update()


RED = '#FF0000'
ORANGE = '#FF8000'
GREEN = '#008000'
BLUE = '#0000FF'
LIGHTER = {RED: '#FFC0C0', ORANGE: '#FFE0C0', GREEN: '#C0E0C0', BLUE: '#C0C0FF'}
IDENTITY = {color: color for color in LIGHTER.keys()}
OPTS = ['AdagradOptimizer', 'AdamOptimizer', 'GradientDescentOptimizer', 'MomentumOptimizer']
OPT_COLORS = {'AdagradOptimizer': RED,
              'AdamOptimizer': ORANGE,
              'GradientDescentOptimizer': GREEN,
              'MomentumOptimizer': BLUE
              }
_NO_DATA = []
OPT_LINES = [Line2D(_NO_DATA, _NO_DATA, color=OPT_COLORS[opt]) for opt in OPTS]


def _plot_history_hyperparams(step_num: int, update_history: Iterable[HyperparamsUpdate], zorder: float,
                              kp_ax: Axes, opt_ax: Axes, mom_ax: Axes) -> None:
    if zorder > 1:
        colormap = IDENTITY
    else:
        colormap = LIGHTER
    current_opt = None
    # Keep probability data
    kp_step_nums = []
    kps = []
    # Learning rate data since the optimizer last changed
    lr_step_nums = []
    log_lrs = []
    # Momentum data since the optimizer last became MomentumOptimizer
    mom_step_nums = []
    moms = []
    for update in update_history:
        new_opt = update.hyperparams['Optimizer']
        if new_opt != current_opt:
            if current_opt is not None:
                # Finish and plot a segment of learning rate data
                last_log_lr = log_lrs[-1]
                lr_step_nums.append(update.step_num)
                log_lrs.append(last_log_lr)
                opt_ax.step(lr_step_nums, log_lrs,
                            colormap[OPT_COLORS[current_opt]], where='post', zorder=zorder)
                # Start a new one
                lr_step_nums = [update.step_num]
                log_lrs = [last_log_lr]
                if current_opt == 'MomentumOptimizer':
                    # Finish and plot a segment of momentum data
                    last_mom = moms[-1]
                    mom_step_nums.append(update.step_num)
                    moms.append(last_mom)
                    mom_ax.step(mom_step_nums, moms, colormap[BLUE], where='post', zorder=zorder)
                    # Start a new one
                    mom_step_nums = []
                    moms = []
            current_opt = new_opt
        # Add the new update to the appropriate data
        kp_step_nums.append(update.step_num)
        kps.append(float(update.hyperparams['Keep probability']))
        lr_step_nums.append(update.step_num)
        log_lrs.append(math.log(float(update.hyperparams['Learning rate']), 10))
        if current_opt == 'MomentumOptimizer':
            mom_step_nums.append(update.step_num)
            moms.append(float(update.hyperparams['Momentum']))
    # Plot the keep probability data
    kp_step_nums.append(step_num)
    kps.append(kps[-1])
    kp_ax.step(kp_step_nums, kps, colormap[BLUE], where='post', zorder=zorder)
    # Finish and plot the last segment of learning rate data
    lr_step_nums.append(step_num)
    log_lrs.append(log_lrs[-1])
    opt_ax.step(lr_step_nums, log_lrs, colormap[OPT_COLORS[current_opt]], where='post', zorder=zorder)
    if current_opt == 'MomentumOptimizer':
        # Finish and plot the last segment of momentum data
        mom_step_nums.append(step_num)
        moms.append(moms[-1])
        mom_ax.step(mom_step_nums, moms, colormap[BLUE], where='post', zorder=zorder)


def plot_hyperparams(info: List[Tuple[int, List[HyperparamsUpdate], float]], peak_value, directory: str) -> None:
    """
    Creates step plots of the hyperparameter update histories of ConvNets with
    the specified information and saves them as images in <directory>.

    <info> is a list of tuples, each corresponding to a ConvNet and containing
    its step number, hyperparameter update history, and accuracy in that order.
    <peak_info> is the value of a ConvNet that achieved the population's
    all-time highest accuracy; this ConvNet's history will be displayed
    specially marked in the plots. <directory> will be created if it does not
    already exist.
    """
    print('Plotting hyperparameters')
    max_step_num = max(max(graph_info[0] for graph_info in info), peak_value[0])
    # Keep probability plot
    kp_fig, kp_ax = plt.subplots()
    kp_ax.set(title='Dropout keep probability', xlabel='Step', ylabel='Keep probability')
    kp_ax.set_xlim(0, max_step_num)
    kp_ax.set_ylim(-0.01, 1.01)
    # Optimizer and learning rate plot
    opt_fig, opt_ax = plt.subplots()
    opt_ax.set(title='Optimizer and learning rate', xlabel='Step', ylabel='Learning rate (log)')
    opt_ax.set_xlim(0, max_step_num)
    opt_ax.set_ylim(-6.06, 0.06)
    opt_ax.legend(OPT_LINES, OPTS, loc='best')
    # Momentum plot
    mom_fig, mom_ax = plt.subplots()
    mom_ax.set(title='Momentum optimizer momentum', xlabel='Step', ylabel='Momentum')
    mom_ax.set_xlim(0, max_step_num)
    mom_ax.set_ylim(-0.01, 1.01)
    # Add data to plots
    peak_updates = []
    update = peak_value[3]
    while update is not None:
        peak_updates.append(update)
        update = update.prev
    _plot_history_hyperparams(peak_value[0], reversed(peak_updates), 2, kp_ax, opt_ax, mom_ax)
    for graph_info in info:
        _plot_history_hyperparams(graph_info[0], graph_info[1], graph_info[2], kp_ax, opt_ax, mom_ax)
    # Save plots
    if not os.path.exists(directory):
        os.makedirs(directory)
    kp_fig.savefig(os.path.join(directory, 'keep_probability.png'))
    opt_fig.savefig(os.path.join(directory, 'optimizer_and_learning_rate.png'))
    mom_fig.savefig(os.path.join(directory, 'momentum.png'))
    print('Hyperparameter plots saved in directory:', directory)
