import torch
import torch.nn as nn

#import numpy as np
#from scipy.stats import entropy

class ConvPoolAc(nn.Module):
    def __init__(self, chanIn, chanOut, kernel=3, stride=1, padding=1, p_ceil_mode=False,bias=True):
        super(ConvPoolAc, self).__init__()

        self.layer = nn.Sequential(
            nn.Conv2d(chanIn, chanOut, kernel_size=kernel,
                stride=stride, padding=padding, bias=bias),
            nn.MaxPool2d(2, stride=2, ceil_mode=p_ceil_mode), #ksize, stride
            nn.ReLU(True)
        )

    def forward(self, x):
        return self.layer(x)

#def _exit_criterion(x, exit_threshold): #NOT for batch size > 1
#    #evaluate the exit criterion on the result provided
#    #return true if it can exit, false if it can't
#    with torch.no_grad():
#        #print(x)
#        softmax_res = nn.functional.softmax(x, dim=-1)
#        #apply scipy.stats.entropy for branchynet,
#        #when they do theirs, its on a batch
#        #print(softmax_res)
#        entr = entropy(softmax_res[-1])
#        #print(entr)
#        return entr < exit_threshold
#
#@torch.jit.script
#def _fast_inf_forward(x, backbone, exits, exit_threshold):
#    for i in range(len(backbone)):
#        x = backbone[i](x)
#        ec = exits[i](x)
#        res = ec
#        if _exit_criterion(ec):
#            break
#    return res

#Main Network
class B_Lenet(nn.Module):
    def __init__(self, exit_threshold=0.5):
        super(B_Lenet, self).__init__()

        # call function to build layers
            #probably need to fragment the model into a moduleList
            #having distinct indices to compute the classfiers/branches on
        #function for building the branches
            #this includes the individual classifier layers, can keep separate
            #last branch/classif being terminal linear layer-included here not main net

        self.fast_inference_mode = False
        #self.fast_inf_batch_size = fast_inf_batch_size #add to input args if used
        #self.exit_fn = entropy
        self.exit_threshold = torch.tensor([exit_threshold], dtype=torch.float32) #TODO learnable, better default value

        self.backbone = nn.ModuleList()
        self.exits = nn.ModuleList()
        self.exit_loss_weights = [1.0, 0.3] #weighting for each exit when summing loss

        #weight initialisiation - for standard layers this is done automagically
        self._build_backbone()
        self._build_exits()

    def _build_backbone(self):
        #Starting conv2d layer
        c1 = nn.Conv2d(1, 5, kernel_size=5, stride=1, padding=3)
        #down sampling is duplicated in original branchynet code
        c1_down_samp_activ = nn.Sequential(
                nn.MaxPool2d(2,stride=2),
                nn.ReLU(True)
                )
        #remaining backbone
        c2 = ConvPoolAc(5, 10, kernel=5, stride=1, padding=3, p_ceil_mode=True)
        c3 = ConvPoolAc(10, 20, kernel=5, stride=1, padding=3, p_ceil_mode=True)
        fc1 = nn.Sequential(nn.Flatten(), nn.Linear(720,84))
        post_ee_layers = nn.Sequential(c1_down_samp_activ,c2,c3,fc1)

        self.backbone.append(c1)
        self.backbone.append(post_ee_layers)

    def _build_exits(self): #adding early exits/branches
        #early exit 1
        ee1 = nn.Sequential(
            nn.MaxPool2d(2, stride=2), #ksize, stride
            nn.ReLU(True),
            ConvPoolAc(5, 10, kernel=3, stride=1, padding=1, p_ceil_mode=True),
            nn.Flatten(),
            nn.Linear(640,10, bias=False),
        )
        self.exits.append(ee1)

        #final exit
        eeF = nn.Sequential(
            nn.Linear(84,10, bias=False),
        )
        self.exits.append(eeF)

    def exit_criterion(self, x): #NOT for batch size > 1
        #evaluate the exit criterion on the result provided
        #return true if it can exit, false if it can't
        with torch.no_grad():
            #NOTE brn exits do not compute softmax in our case
            pk = nn.functional.softmax(x, dim=-1)
            #apply scipy.stats.entropy for branchynet,
            #when they do theirs, its on a batch - same calc bu pt
            entr = -torch.sum(pk * torch.log(pk))
            #print("entropy:",entr)
            return entr < self.exit_threshold

    def exit_criterion_top1(self, x): #NOT for batch size > 1
        #evaluate the exit criterion on the result provided
        #return true if it can exit, false if it can't
        with torch.no_grad():
            pk = nn.functional.softmax(x, dim=-1)
            top1 = torch.max(pk) #x)
            return top1 > self.exit_threshold

    @torch.jit.unused #decorator to skip jit comp
    def _forward_training(self, x):
        #TODO make jit compatible - not urgent
        #broken because returning list()
        res = []
        for bb, ee in zip(self.backbone, self.exits):
            x = bb(x)
            res.append(ee(x))
        return res

    def forward(self, x):
        #std forward function - add var to distinguish be test and inf

        if self.fast_inference_mode:
            for bb, ee in zip(self.backbone, self.exits):
                x = bb(x)
                res = ee(x) #res not changed by exit criterion
                if self.exit_criterion_top1(res):
                    #print("EE fired")
                    return res
            return res

            #works for predefined batchsize - pytorch only for same reason of batching
            '''
            mb_chunk = torch.chunk(x, self.fast_inf_batch_size, dim=0)
            res_temp=[]
            for xs in mb_chunk:
                for j in range(len(self.backbone)):
                    xs = self.backbone[j](xs)
                    ec = self.exits[j](xs)
                    if self.exit_criterion(ec):
                        break
                res_temp.append(ec)
            print("RESTEMP", res_temp)
            res = torch.cat(tuple(res_temp), 0)
            '''

        else: #used for training
            #calculate all exits
            return self._forward_training(x)

    def set_fast_inf_mode(self, mode=True):
        if mode:
            self.eval()
        self.fast_inference_mode = mode

#FPGAConvNet friendly version:
#ceiling mode flipped, FC layer sizes adapted, padding altered,removed duplicated layers
class B_Lenet_fcn(B_Lenet):
    def _build_backbone(self):
        strt_bl = ConvPoolAc(1, 5, kernel=5, stride=1, padding=4)
        self.backbone.append(strt_bl)

        #adding ConvPoolAc blocks - remaining backbone
        bb_layers = []
        bb_layers.append(ConvPoolAc(5, 10, kernel=5, stride=1, padding=4) )
        bb_layers.append(ConvPoolAc(10, 20, kernel=5, stride=1, padding=3) )
        bb_layers.append(nn.Flatten())
        bb_layers.append(nn.Linear(720, 84, bias=False))

        remaining_backbone_layers = nn.Sequential(*bb_layers)
        self.backbone.append(remaining_backbone_layers)

    #adding early exits/branches
    def _build_exits(self):
        #early exit 1
        ee1 = nn.Sequential(
            ConvPoolAc(5, 10, kernel=3, stride=1, padding=1),
            nn.Flatten(),
            nn.Linear(640,10, bias=False),
            )
        self.exits.append(ee1)

        #final exit
        eeF = nn.Sequential(
            nn.Linear(84,10, bias=False),
        )
        self.exits.append(eeF)

#Simplified exit version:
#stacks on _fcn changes, removes the conv
class B_Lenet_se(B_Lenet):
    def _build_backbone(self):
        strt_bl = ConvPoolAc(1, 5, kernel=5, stride=1, padding=4)
        self.backbone.append(strt_bl)

        #adding ConvPoolAc blocks - remaining backbone
        bb_layers = []
        bb_layers.append(ConvPoolAc(5, 10, kernel=5, stride=1, padding=4) )
        bb_layers.append(ConvPoolAc(10, 20, kernel=5, stride=1, padding=3) )
        bb_layers.append(nn.Flatten())
        bb_layers.append(nn.Linear(720, 84, bias=False))

        remaining_backbone_layers = nn.Sequential(*bb_layers)
        self.backbone.append(remaining_backbone_layers)

    #adding early exits/branches
    def _build_exits(self):
        #early exit 1
        ee1 = nn.Sequential(
            nn.Flatten(),
            nn.Linear(1280,10, bias=False),
            )
        self.exits.append(ee1)

        #final exit
        eeF = nn.Sequential(
            nn.Linear(84,10, bias=False),
        )
        self.exits.append(eeF)
