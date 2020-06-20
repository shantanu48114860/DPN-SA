import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

from Sparse_Propensity_net import Sparse_Propensity_net
from Utils import Utils


class Sparse_Propensity_score:
    def train(self, train_parameters, device, phase):
        print(".. Training started ..")
        epochs = train_parameters["epochs"]
        batch_size = train_parameters["batch_size"]
        lr = train_parameters["lr"]
        shuffle = train_parameters["shuffle"]
        model_save_path = train_parameters["model_save_path"].format(epochs, lr)
        train_set = train_parameters["train_set"]

        sparsity_probability = train_parameters["sparsity_probability"],
        weight_decay = train_parameters["weight_decay"]
        BETA = train_parameters["weight_decay"]
        print("Saved model path: {0}".format(model_save_path))

        data_loader = torch.utils.data.DataLoader(train_set, batch_size=batch_size,
                                                  shuffle=shuffle, num_workers=4)
        sae_network = self.train_SAE(epochs, device, data_loader, lr, weight_decay, sparsity_probability, BETA,
                                     phase)

        sparse_classifier = nn.Sequential(*list(sae_network.children())[:-1])
        sparse_classifier.add_module('classifier',
                                     nn.Sequential(nn.Linear(in_features=1, out_features=2),
                                                   nn.LogSoftmax(dim=1)))
        sparse_classifier = sparse_classifier.to(device)
        sparse_classifier = self.train_classifier(train_set, device, phase, sparse_classifier)


        # print("Saving model..")
        # saved_parameters = sae_network.state_dict()
        # del saved_parameters['decoder1.weight']
        # del saved_parameters['decoder2.weight']
        # # del saved_parameters['decoder3.weight']
        # del saved_parameters['decoder1.bias']
        # del saved_parameters['decoder2.bias']
        # # del saved_parameters['decoder3.bias']
        # torch.save(saved_parameters, model_save_path)

        print("Training completed..")
        return sparse_classifier

    def train_SAE(self, epochs, device, data_loader, lr, weight_decay=0.0005,
                  sparsity_probability=0.03,
                  BETA=0.001, training_mode="train"):
        print("----- Training SAE -----")
        network = Sparse_Propensity_net(training_mode=training_mode, device=device).to(device)
        criterion = nn.MSELoss()
        # the optimizer
        optimizer = optim.Adam(network.parameters(), lr=lr, weight_decay=weight_decay)
        model_children = list(network.children())

        for epoch in range(epochs):
            network.train()
            total_loss = 0
            counter = 0
            train_set_size = 0

            for batch in data_loader:
                counter += 1
                covariates, _ = batch
                covariates = covariates.to(device)
                covariates = covariates[:, :-2]
                train_set_size += covariates.size(0)

                treatment_pred = network(covariates)
                mse_loss = criterion(treatment_pred, covariates)
                sparsity = self.sparse_loss(sparsity_probability, covariates, model_children, device)
                loss = mse_loss + BETA * sparsity
                # loss = mse_loss
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                total_loss += loss.item()

            epoch_loss = total_loss / counter
            print("Epoch: {0}, loss: {1}".
                  format(epoch, epoch_loss))

        return network

    @staticmethod
    def train_classifier(train_set, device, phase, sparse_classifier):
        print(device)
        # sparse_classifier[0][0].weight.requires_grad = False
        # sparse_classifier[0][0].bias.requires_grad = False
        # sparse_classifier[0][2].weight.requires_grad = False
        # sparse_classifier[0][2].bias.requires_grad = False
        print(".. Propensity score evaluation started using Sparse AE..")

        data_loader = torch.utils.data.DataLoader(train_set, batch_size=32,
                                                  shuffle=True, num_workers=4)
        criterion = nn.NLLLoss()
        optimizer = optim.Adam(sparse_classifier.parameters(), lr=0.01)
        for epoch in range(100):
            sparse_classifier.train()
            total_loss = 0
            total_correct = 0
            train_set_size = 0

            for batch in data_loader:
                covariates, treatment = batch
                covariates = covariates.to(device)
                train_set_size += covariates.size(0)

                treatment = treatment.squeeze().to(device)
                covariates = covariates[:, :-2]
                treatment_pred = sparse_classifier(covariates).to(device)

                loss = criterion(treatment_pred, treatment)

                optimizer.zero_grad()
                loss.backward(retain_graph=True)
                optimizer.step()

                total_loss += loss.item()
                _, preds = torch.max(treatment_pred.data, 1)
                total_correct += torch.sum(preds == treatment.data)

            pred_accuracy = total_correct.item() / train_set_size
            print("Epoch: {0}, loss: {1}, correct: {2}/{3}, accuracy: {4}".
                  format(epoch, total_loss, total_correct, train_set_size, pred_accuracy))

        return sparse_classifier

    @staticmethod
    def sparse_loss(sparsity_probability, covariates, model_children, device):
        values = covariates
        loss = 0
        for i in range(len(model_children)):
            values = model_children[i](values)
            loss += Utils.KL_divergence(sparsity_probability, values, device)
        return loss

    @staticmethod
    def eval(eval_set, device, phase, sparse_classifier):
        print(".. Propensity score evaluation started using Sparse AE ..")
        sparse_classifier.eval()
        data_loader = torch.utils.data.DataLoader(eval_set, shuffle=False, num_workers=4)
        total_correct = 0
        eval_set_size = 0
        prop_score_list = []
        total_correct = 0

        for batch in data_loader:
            covariates, treatment = batch
            covariates = covariates.to(device)
            covariates = covariates[:, :-2]
            treatment = treatment.squeeze().to(device)

            eval_set_size += covariates.size(0)

            treatment_pred = sparse_classifier(covariates).to(device)
            treatment_pred_prob = F.softmax(treatment_pred, dim=1)
            # print(treatment_pred_prob)
            treatment_pred_prob = treatment_pred_prob.squeeze()
            prop_score_list.append(treatment_pred_prob[1].item())

            _, preds = torch.max(treatment_pred.data, 1)
            total_correct += torch.sum(preds == treatment.data)

        pred_accuracy = total_correct.item() / eval_set_size
        # print("Accuracy: {0}".format(total_correct))
        # print("correct: {0}, accuracy: {1}".format(total_correct, pred_accuracy))
        print(".. Propensity score evaluation completed Sparse AE ..")
        return prop_score_list
