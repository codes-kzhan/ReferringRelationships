"""Define the referring relationship model.
"""

from keras import backend as K
from keras.applications.resnet50 import ResNet50
from keras.layers import Dense, Flatten, UpSampling2D, Input, Activation
from keras.layers.convolutional import Conv2DTranspose, Conv2D
from keras.layers.core import Lambda, Dropout, Reshape
from keras.layers.embeddings import Embedding
from keras.layers.merge import Multiply, Dot
from keras.models import Model

import numpy as np

from config import parse_args


class ReferringRelationshipsModel():
    """Given a relationship, this model locatlizes them.
    """

    def __init__(self, args):
        """Constructor for ReferringRelationshipModel.

        Args:
            args: the arguments specified by `config.py`.
        """
        self.input_dim = args.input_dim
        self.feat_map_dim = args.feat_map_dim
        self.hidden_dim = args.hidden_dim
        self.embedding_dim = args.embedding_dim
        self.num_predicates = args.num_predicates
        self.num_objects = args.num_objects
        self.dropout = args.dropout
        self.use_subject = args.use_subject
        self.use_predicate = args.use_predicate
        self.use_object = args.use_object

    def build_model(self):
        """Initializes the SSN model.

        Returns:
            The Keras model.
        """
        input_im = Input(shape=(self.input_dim, self.input_dim, 3))
        input_subj = Input(shape=(1,))
        input_pred = Input(shape=(1,))
        input_obj = Input(shape=(1,))
        im_features = self.build_image_model(input_im)
        obj_subj_embedding = self.build_embedding_layer(self.num_objects, self.hidden_dim)
        predicate_embedding = self.build_embedding_layer(self.num_predicates, (self.feat_map_dim)**4)
        embedded_subject = obj_subj_embedding(input_subj)
        embedded_predicate = predicate_embedding(input_pred)
        embedded_object = obj_subj_embedding(input_obj)
        subject_att = self.build_attention_layer(im_features, embedded_subject)
        predicate_att = self.build_map_transform_layer_dense(subject_att, embedded_predicate)
        predicate_map = Multiply()([im_features, predicate_att])
        object_att = self.build_attention_layer(predicate_map, embedded_object)
        subject_regions = self.build_upsampling_layer(subject_att, "subject_att")
        subject_regions_flat = Flatten(name="subject")(subject_regions)
        object_regions = self.build_upsampling_layer(object_att, "object_att")
        object_regions_flat = Flatten(name="object")(object_regions)
        model = Model(inputs=[input_im, input_subj, input_pred, input_obj], outputs=[subject_regions_flat, object_regions_flat])
        return model

    def build_image_model(self, input_im):
        """Grab the image features.

        Args:
            input_im: The input image to the model.

        Returns:
            The image feature map.
        """
        base_model = ResNet50(weights='imagenet',
                              include_top=False,
                              input_shape=(self.input_dim, self.input_dim, 3))
        for layer in base_model.layers:
            layer.trainable = False
        output = base_model.get_layer('activation_49').output 
        image_branch = Model(inputs=base_model.input, outputs=output)
        im_features = image_branch(input_im)
        return im_features

    def build_map_transform_layer_dense(self, att_weights, pred_features):
        att_weights_flat = Reshape((1, self.feat_map_dim**2))(att_weights) # N x H
        pred_matrix = Reshape((self.feat_map_dim**2, self.feat_map_dim**2))(pred_features) # H x H
        att_transformed = Multiply()([att_weights_flat, pred_matrix])
        att_transformed = Lambda(lambda x: K.sum(x, axis=2))(att_transformed)
        att_transformed = Activation('sigmoid')(att_transformed)
        att_transformed = Reshape((self.feat_map_dim, self.feat_map_dim, 1))(att_transformed)
        return att_transformed
    
    def build_map_transform_layer_conv(self, att_weights, query):
        conv_map = Conv2D(self.hidden_dim, 3, padding='same')(att_weights)
        att_transformed = Multiply()([conv_map, query])
        att_transformed = Lambda(lambda x: K.sum(x, axis=3, keepdims=True))(att_transformed)
        att_transformed = Activation('sigmoid')(att_transformed)
        return att_transformed

    def build_embedding_layer(self, num_categories, emb_dim):
        return Embedding(num_categories, emb_dim, input_length=1)

    def build_attention_layer(self, feature_map, query):
        attention_weights = Multiply()([feature_map, query])
        attention_weights = Lambda(lambda x: K.sum(x, axis=3, keepdims=True))(attention_weights)
        attention_weights = Activation('sigmoid')(attention_weights)
        return attention_weights

    def build_frac_strided_transposed_conv_layer(self, conv_layer):
        res = UpSampling2D(size=(2, 2))(conv_layer)
        res = Conv2DTranspose(1, 3, padding='same')(res)
        return res

    def build_upsampling_layer(self, feature_map, layer_name):
        upsampling_factor = self.input_dim / self.feat_map_dim
        k = int(np.log(upsampling_factor) / np.log(2))
        res = feature_map
        for i in range(k):
            res = self.build_frac_strided_transposed_conv_layer(res)
        predictions = Activation('sigmoid', name=layer_name)(res)
        return predictions
    

if __name__ == "__main__":
    args = parse_args()
    rel = ReferringRelationshipsModel(args)
    model = rel.build_model()
    model.summary()