# Copyright 2019 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Imports a convolutional feature extractor for MNIST in SavedModel format.

This program picks up the SavedModel written by export_mnist_cnn.py and
uses the feature extractor contained in it to classification on either
classic MNIST (digits) or Fashion MNIST (thumbnails of apparel). Optionally,
it trains the feature extractor further as part of the new classifier.
As expected, that makes training slower but does not help much for the
original training dataset but helps a lot for transfer to the other dataset.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from absl import app
from absl import flags
import tensorflow as tf

from tensorflow.examples.saved_model.integration_tests import mnist_util
from tensorflow.examples.saved_model.integration_tests import util
from tensorflow.python.saved_model import load as svmd_load
tf.saved_model.load = svmd_load.load

FLAGS = flags.FLAGS

flags.DEFINE_string(
    'export_dir', None,
    'Directory of exported SavedModel.')
flags.DEFINE_integer(
    'epochs', 5,
    'Number of epochs to train.')
flags.DEFINE_bool(
    'retrain', False,
    'If set, the imported SavedModel is trained further.')
flags.DEFINE_float(
    'dropout_rate', None,
    'If set, dropout rate passed to the SavedModel.')
flags.DEFINE_float(
    'regularization_loss_multiplier', None,
    'If set, multiplier for the regularization losses in the SavedModel.')
flags.DEFINE_bool(
    'use_fashion_mnist', False,
    'Use Fashion MNIST (products) instead of the real MNIST (digits). '
    'With this, --retrain gains a lot.')
flags.DEFINE_bool(
    'fast_test_mode', False,
    'Shortcut training for running in unit tests.')


def make_classifier(feature_extractor, l2_strength=0.01, dropout_rate=0.5):
  """Returns a Keras Model to classify MNIST using feature_extractor."""
  regularizer = lambda: tf.keras.regularizers.l2(l2_strength)
  net = inp = tf.keras.Input(mnist_util.INPUT_SHAPE)
  net = feature_extractor(net)
  net = tf.keras.layers.Dropout(dropout_rate)(net)
  net = tf.keras.layers.Dense(mnist_util.NUM_CLASSES, activation='softmax',
                              kernel_regularizer=regularizer())(net)
  return tf.keras.Model(inputs=inp, outputs=net)


def scale_regularization_losses(obj, multiplier):
  """Scales obj.regularization_losses by multiplier if not None."""
  if multiplier is None: return
  def _scale_one_loss(l):  # Separate def avoids lambda capture of loop var.
    f = tf.function(lambda: tf.multiply(multiplier, l()))
    _ = f.get_concrete_function()
    return f
  obj.regularization_losses = [_scale_one_loss(l)
                               for l in obj.regularization_losses]


def main(argv):
  del argv

  # Load a pre-trained feature extractor and wrap it for use in Keras.
  obj = tf.saved_model.load(FLAGS.export_dir)
  scale_regularization_losses(obj, FLAGS.regularization_loss_multiplier)
  arguments = {}
  if FLAGS.dropout_rate is not None:
    arguments['dropout_rate'] = FLAGS.dropout_rate
  feature_extractor = util.CustomLayer(obj, output_shape=[128],
                                       trainable=FLAGS.retrain,
                                       arguments=arguments)

  # Build a classifier with it.
  model = make_classifier(feature_extractor)

  # Train the classifier (possibly on a different dataset).
  (x_train, y_train), (x_test, y_test) = mnist_util.load_reshaped_data(
      use_fashion_mnist=FLAGS.use_fashion_mnist,
      fake_tiny_data=FLAGS.fast_test_mode)
  model.compile(loss=tf.keras.losses.categorical_crossentropy,
                optimizer=tf.keras.optimizers.SGD(),
                metrics=['accuracy'],
                # TODO(arnoegw): Remove after investigating huge allocs.
                run_eagerly=True)
  print('Training on %s with %d trainable and %d untrainable variables.' %
        ('Fashion MNIST' if FLAGS.use_fashion_mnist else 'MNIST',
         len(model.trainable_variables), len(model.non_trainable_variables)))
  model.fit(x_train, y_train,
            batch_size=128,
            epochs=FLAGS.epochs,
            steps_per_epoch=3,
            verbose=1,
            validation_data=(x_test, y_test))


if __name__ == '__main__':
  # tf.enable_v2_behavior()
  app.run(main)
