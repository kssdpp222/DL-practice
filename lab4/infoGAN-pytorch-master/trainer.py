import torch
import torch.nn as nn
import torch.optim as optim
from torch.autograd import Variable
import torch.autograd as autograd

import torchvision.datasets as dset
import torchvision.transforms as transforms
from torch.utils.data import DataLoader
from torchvision.utils import save_image
import matplotlib.pyplot as plt
from torch.autograd import Variable
import numpy as np

class log_gaussian:

  def __call__(self, x, mu, var):

    logli = -0.5*(var.mul(2*np.pi)+1e-6).log() - \
            (x-mu).pow(2).div(var.mul(2.0)+1e-6)
    
    return logli.sum(1).mean().mul(-1)

def detailOfTensor(Tensor):
    print(Tensor,Tensor.dtype,Tensor.size(),Tensor.device)

noise_size = 52
c_size = 10

class Trainer:

  def __init__(self, G, FE, D, Q):

    self.G = G
    self.FE = FE
    self.D = D
    self.Q = Q

    self.batch_size = 100

  def _noise_sample(self, dis_c, con_c, noise, bs):

    idx = np.random.randint(10, size=bs)
    c = np.zeros((bs, 10))
    c[range(bs),idx] = 1.0

    dis_c.data.copy_(torch.Tensor(c))
    con_c.data.uniform_(-1.0, 1.0)
    noise.data.uniform_(-1.0, 1.0)
    z = torch.cat([noise, dis_c, con_c], 1).view(-1, 64, 1, 1)

    return z, idx

  def train(self):

    real_x = torch.FloatTensor(self.batch_size, 1, 64, 64).cuda()
    label = torch.FloatTensor(self.batch_size, 1).cuda()
    dis_c = torch.FloatTensor(self.batch_size, 10).cuda()
    con_c = torch.FloatTensor(self.batch_size, 2).cuda()
    noise = torch.FloatTensor(self.batch_size, noise_size).cuda()

    real_x = Variable(real_x)
    label = Variable(label, requires_grad=False)
    dis_c = Variable(dis_c)
    con_c = Variable(con_c)
    noise = Variable(noise)

    criterionD = nn.BCELoss().cuda()
    criterionQ_dis = nn.CrossEntropyLoss().cuda()
    criterionQ_con = log_gaussian()

    optimD = optim.Adam([{'params':self.FE.parameters()}, {'params':self.D.parameters()}], lr=0.0002, betas=(0.5, 0.99))
    optimG = optim.Adam([{'params':self.G.parameters()}, {'params':self.Q.parameters()}], lr=0.001, betas=(0.5, 0.99))

    dataset = dset.MNIST('./dataset', download=True,
                           transform=transforms.Compose([
                               transforms.Resize(64),
                               transforms.ToTensor(),
                               transforms.Normalize((0.5,), (0.5,)),
                           ]))
    
    dataloader = DataLoader(dataset, batch_size=self.batch_size, shuffle=True, num_workers=1)

    # fixed random variables
    c = np.linspace(-1, 1, 10).reshape(1, -1)
    c = np.repeat(c, 10, 0).reshape(-1, 1)

    c1 = np.hstack([c, np.zeros_like(c)])
    c2 = np.hstack([np.zeros_like(c), c])

    idx = np.arange(10).repeat(10)
    one_hot = np.zeros((100, 10))
    one_hot[range(100), idx] = 1
    fix_noise = torch.Tensor(100, noise_size).uniform_(-1, 1)
    fig = plt.figure()
    ax1 = fig.add_subplot(121)
    ax2 = fig.add_subplot(122)
    ax1.set_title('G Loss')
    ax2.set_title('D Loss')

    G_loss_list = []
    D_loss_list = []
    x_axis = [ i for i in range(1,50 * 600 + 1)] 
    for epoch in range(1,50+1):
      for num_iters, batch_data in enumerate(dataloader, 0):

        # real part
        optimD.zero_grad()
        
        x, _ = batch_data

        bs = x.size(0)
        real_x.data.resize_(x.size())
        label.data.resize_(bs, 1)
        dis_c.data.resize_(bs, 10)
        con_c.data.resize_(bs, 2)
        noise.data.resize_(bs, noise_size)
        
        real_x.data.copy_(x)
        fe_out1 = self.FE(real_x)
        probs_real = self.D(fe_out1)
        
        label.data.fill_(1)
        loss_real = criterionD(probs_real, label)
        loss_real.backward()

        # fake part
        z, idx = self._noise_sample(dis_c, con_c, noise, bs)
        fake_x = self.G(z)
        fe_out2 = self.FE(fake_x.detach())
        probs_fake = self.D(fe_out2)
        label.data.fill_(0)
        loss_fake = criterionD(probs_fake, label)
        loss_fake.backward()

        D_loss = loss_real + loss_fake
        D_loss_list.append(D_loss.data.cpu().numpy())
        if D_loss > 0.01:
          optimD.step()
        
        
        # G and Q part
        optimG.zero_grad()

        fe_out = self.FE(fake_x)
        probs_fake = self.D(fe_out)
        label.data.fill_(1.0)

        reconstruct_loss = criterionD(probs_fake, label)
        
        q_logits, q_mu, q_var = self.Q(fe_out)
        class_ = torch.LongTensor(idx).cuda()
        target = Variable(class_)
        dis_loss = criterionQ_dis(q_logits, target)
        con_loss = criterionQ_con(con_c, q_mu, q_var)*0.1
        
        G_loss = reconstruct_loss + dis_loss + con_loss
        G_loss_list.append(G_loss.data.cpu().numpy())
       
        G_loss.backward()
        optimG.step()

        if num_iters % 100 == 0:

          print('Epoch/Iter:{0}/{1}, Dloss: {2}, Gloss: {3}'.format(
            epoch, num_iters, D_loss.data.cpu().numpy(),
            G_loss.data.cpu().numpy())
          )
         
          noise.data.copy_(fix_noise)
          dis_c.data.copy_(torch.Tensor(one_hot))

          con_c.data.copy_(torch.from_numpy(c1))
          z = torch.cat([noise, dis_c, con_c], 1).view(-1, 64, 1, 1)
          x_save = self.G(z)
          

          con_c.data.copy_(torch.from_numpy(c2))
          z = torch.cat([noise, dis_c, con_c], 1).view(-1, 64, 1, 1)
          x_save = self.G(z)
         
      torch.save(self.G.state_dict(), "G_{}.h5".format(epoch))
      save_image(x_save.data, './tmp/c1_{}.png'.format(epoch), nrow=10)  
      save_image(x_save.data, './tmp/c2_{}.png'.format(epoch), nrow=10)
    ax1.plot(x_axis,G_loss_list, color="red")
    ax2.plot(x_axis,D_loss_list, color="red")
    plt.savefig('result.png',dpi = 200)
    