#!/usr/bin/env python3

"""
Implements the Dragonfly (SAE) handshake.

Instead of using a client (STA) and a access point (AP), we
just programmatically create a peer to peer network of two participiants.
Either party may initiate the SAE protocol, either party can be the client and server.

In a mesh scenario, where two APs (two equals) are trying to establish a connection
between each other and each one could have the role of supplicant or authenticator.

SAE is build upon the Dragonfly Key Exchange, which is described in https://tools.ietf.org/html/rfc7664.

https://stackoverflow.com/questions/31074172/elliptic-curve-point-addition-over-a-finite-field-in-python
"""
import time
import hashlib
import random
import logging
from collections import namedtuple
import json
import subprocess
import os 
import os.path
import struct
import csv

import base64
from Cryptodome.Cipher import AES
from Cryptodome import Random
from Cryptodome.Protocol.KDF import PBKDF2

#------------------------------------------------------------------------------------------
 
# load additional Python module
import socket
import re, uuid
# create TCP/IP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# retrieve local hostname
local_hostname = socket.gethostname()

# get fully qualified hostname
local_fqdn = socket.getfqdn()

# get the according IP address
ip_address = socket.gethostbyname(local_hostname)

# output hostname, domain name and IP address
print ("working on %s (%s) with %s" % (local_hostname, local_fqdn, ip_address))

# bind the socket to the port 23456
server_address = ('192.168.0.100', 23456)  
print ('starting up on %s port %s' % server_address)  
sock.bind(server_address)

#---------------------------------------------------------------------------------------------

logger = logging.getLogger('dragonfly')
logger.setLevel(logging.INFO)
# create file handler which logs even debug messages
fh = logging.FileHandler('dragonfly.log')
fh.setLevel(logging.DEBUG)
# create console handler with a higher log level
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
# create formatter and add it to the handlers
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
fh.setFormatter(formatter)
# add the handlers to logger
logger.addHandler(ch)
logger.addHandler(fh)

#important: tells u datatype
Point = namedtuple("Point", "x y")
# The point at infinity (origin for the group law).
O = 'Origin'

def lsb(x):
    binary = bin(x).lstrip('0b')
    return binary[0]

def legendre(a, p):
    return pow(a, (p - 1) // 2, p)

def tonelli_shanks(n, p):
    """
    # https://rosettacode.org/wiki/Tonelli-Shanks_algorithm#Python
    """
    assert legendre(n, p) == 1, "not a square (mod p)"
    q = p - 1
    s = 0
    while q % 2 == 0:
        q //= 2
        s += 1
    if s == 1:
        return pow(n, (p + 1) // 4, p)
    for z in range(2, p):
        if p - 1 == legendre(z, p):
            break
    c = pow(z, q, p)
    r = pow(n, (q + 1) // 2, p)
    t = pow(n, q, p)
    m = s
    t2 = 0
    while (t - 1) % p != 0:
        t2 = (t * t) % p
        for i in range(1, m):
            if (t2 - 1) % p == 0:
                break
            t2 = (t2 * t2) % p
        b = pow(c, 1 << (m - i - 1), p)
        r = (r * b) % p
        c = (b * b) % p
        t = (t * c) % p
        m = i
    return r

class Curve():
    """
    Mathematical operations on a Elliptic Curve.

    A lot of code taken from:
    https://stackoverflow.com/questions/31074172/elliptic-curve-point-addition-over-a-finite-field-in-python
    """

    def __init__(self, a, b, p):
        self.a = a
        self.b = b
        self.p = p

    def curve_equation(self, x):
        """
        We currently use the elliptic curve
        NIST P-384
        """
        return (pow(x, 3) + (self.a * x) + self.b) % self.p

    def is_quadratic_residue(self, x):
        """
        https://en.wikipedia.org/wiki/Euler%27s_criterion
        Computes Legendre Symbol.
        """
        return pow(x, (self.p-1) // 2, self.p) == 1

    def valid(self, P):
        """
        Determine whether we have a valid representation of a point
        on our curve.  We assume that the x and y coordinates
        are always reduced modulo p, so that we can compare
        two points for equality with a simple ==.
        """
        if P == O:
            return True
        else:
            return (
                (P.y**2 - (P.x**3 + self.a*P.x + self.b)) % self.p == 0 and
                0 <= P.x < self.p and 0 <= P.y < self.p)

    def inv_mod_p(self, x):
        """
        Compute an inverse for x modulo p, assuming that x
        is not divisible by p.
        """
        if x % self.p == 0:
            raise ZeroDivisionError("Impossible inverse")
        return pow(x, self.p-2, self.p)

    def ec_inv(self, P):
        """
        Inverse of the point P on the elliptic curve y^2 = x^3 + ax + b.
        """
        if P == O:
            return P
        return Point(P.x, (-P.y) % self.p)

    def ec_add(self, P, Q):
        """
        Sum of the points P and Q on the elliptic curve y^2 = x^3 + ax + b.
        https://stackoverflow.com/questions/31074172/elliptic-curve-point-addition-over-a-finite-field-in-python
        """
        if not (self.valid(P) and self.valid(Q)):
            raise ValueError("Invalid inputs")

        # Deal with the special cases where either P, Q, or P + Q is
        # the origin.
        if P == O:
            result = Q
        elif Q == O:
            result = P
        elif Q == self.ec_inv(P):
            result = O
        else:
            # Cases not involving the origin.
            if P == Q:
                dydx = (3 * P.x**2 + self.a) * self.inv_mod_p(2 * P.y)
            else:
                dydx = (Q.y - P.y) * self.inv_mod_p(Q.x - P.x)
            x = (dydx**2 - P.x - Q.x) % self.p
            y = (dydx * (P.x - x) - P.y) % self.p
            result = Point(x, y)

        # The above computations *should* have given us another point
        # on the curve.
        assert self.valid(result)
        return result

    def double_add_algorithm(self, scalar, P):
        """
        Double-and-Add Algorithm for Point Multiplication
        Input: A scalar in the range 0-p and a point on the elliptic curve P
        https://stackoverflow.com/questions/31074172/elliptic-curve-point-addition-over-a-finite-field-in-python
        """
        assert self.valid(P)

        b = bin(scalar).lstrip('0b')
        T = P
        for i in b[1:]:
            T = self.ec_add(T, T)
            if i == '1':
                T = self.ec_add(T, P)

        assert self.valid(T)
        return T

class Peer:
    """
    Implements https://wlan1nde.wordpress.com/2018/09/14/wpa3-improving-your-wlan-security/
    Take a ECC curve from here: https://safecurves.cr.yp.to/

    Example: NIST P-384
    y^2 = x^3-3x+27580193559959705877849011840389048093056905856361568521428707301988689241309860865136260764883745107765439761230575
    modulo p = 2^384 - 2^128 - 2^96 + 2^32 - 1
    2000 NIST; also in SEC 2 and NSA Suite B

    See here: https://www.rfc-editor.org/rfc/rfc5639.txt

   Curve-ID: brainpoolP256r1
      p =
      A9FB57DBA1EEA9BC3E660A909D838D726E3BF623D52620282013481D1F6E5377
      A =
      7D5A0975FC2C3057EEF67530417AFFE7FB8055C126DC5C6CE94A4B44F330B5D9
      B =
      26DC5C6CE94A4B44F330B5D9BBD77CBF958416295CF7E1CE6BCCDC18FF8C07B6
      x =
      8BD2AEB9CB7E57CB2C4B482FFC81B7AFB9DE27E1E3BD23C23A4453BD9ACE3262
      y =
      547EF835C3DAC4FD97F8461A14611DC9C27745132DED8E545C1D54C72F046997
      q =
      A9FB57DBA1EEA9BC3E660A909D838D718C397AA3B561A6F7901E0E82974856A7
      h = 1
    """

    def __init__(self, password, mac_address, name):
        self.name = name
        self.password = password
        self.mac_address = mac_address

        # Try out Curve-ID: brainpoolP256t1
        self.p = int('A9FB57DBA1EEA9BC3E660A909D838D726E3BF623D52620282013481D1F6E5377', 16)
        self.a = int('7D5A0975FC2C3057EEF67530417AFFE7FB8055C126DC5C6CE94A4B44F330B5D9', 16)
        self.b = int('26DC5C6CE94A4B44F330B5D9BBD77CBF958416295CF7E1CE6BCCDC18FF8C07B6', 16)
        self.q = int('A9FB57DBA1EEA9BC3E660A909D838D718C397AA3B561A6F7901E0E82974856A7', 16)
        self.curve = Curve(self.a, self.b, self.p)

        # A toy curve
        # self.a, self.b, self.p = 2, 2, 17
        # self.q = 19
        # self.curve = Curve(self.a, self.b, self.p)

    def initiate(self, other_mac, k=40):
        """
        See algorithm in https://tools.ietf.org/html/rfc7664
        in section 3.2.1
        """
        self.other_mac = other_mac
        found = 0
        num_valid_points = 0
        counter = 1
        n = self.p.bit_length() + 64

        while counter <= k:
            base = self.compute_hashed_password(counter)
            temp = self.key_derivation_function(n, base, 'Dragonfly Hunting And Pecking')
            seed = (temp % (self.p - 1)) + 1
            val = self.curve.curve_equation(seed)
            if self.curve.is_quadratic_residue(val):
                if num_valid_points < 5:
                    x = seed
                    save = base
                    found = 1
                    num_valid_points += 1
                    logger.debug('Got point after {} iterations'.format(counter))

            counter = counter + 1

        if found == 0:
            logger.error('No valid point found after {} iterations'.format(k))
        elif found == 1:
            # https://crypto.stackexchange.com/questions/6777/how-to-calculate-y-value-from-yy-mod-prime-efficiently
            # https://rosettacode.org/wiki/Tonelli-Shanks_algorithm
            y = tonelli_shanks(self.curve.curve_equation(x), self.p)

            PE = Point(x, y)

            # check valid point
            assert self.curve.curve_equation(x) == pow(y, 2, self.p)

            logger.info('[{}] Using {}-th valid Point={}'.format(self.name, num_valid_points, PE))
            logger.info('[{}] Point is on curve: {}'.format(self.name, self.curve.valid(PE)))

            self.PE = PE
            assert self.curve.valid(self.PE)

    def commit_exchange(self):
        
        """
        This is basically Diffie Hellman Key Exchange (or in our case ECCDH)

        In the Commit Exchange, both sides commit to a single guess of the
        password.  The peers generate a scalar and an element, exchange them
        with each other, and process the other's scalar and element to
        generate a common and shared secret.

        If we go back to elliptic curves over the real numbers, there is a nice geometric
        interpretation for the ECDLP: given a starting point P, we compute 2P, 3P, . . .,
        d P = T , effectively hopping back and forth on the elliptic curve. We then publish
        the starting point P (a public parameter) and the final point T (the public key). In
        order to break the cryptosystem, an attacker has to figure out how often we “jumped”
        on the elliptic curve. The number of hops is the secret d, the private key.
        """
        # seed the PBG before picking a new random number
        # random.seed(time.process_time())

        # None or no argument seeds from current time or from an operating
        # system specific randomness source if available.
        random.seed()

        # Otherwise, each party chooses two random numbers, private and mask
        self.private = random.randrange(1, self.p)
        self.mask = random.randrange(1, self.p)

        logger.debug('[{}] private={}'.format(self.name, self.private))
        logger.debug('[{}] mask={}'.format(self.name, self.mask))

        # These two secrets and the Password Element are then used to construct
        # the scalar and element:

        # what is q?
        # o  A point, G, on the elliptic curve, which serves as a generator for
        #    the ECC group.  G is chosen such that its order, with respect to
        #    elliptic curve addition, is a sufficiently large prime.
        #
        # o  A prime, q, which is the order of G, and thus is also the size of
        #    the cryptographic subgroup that is generated by G.

        # https://math.stackexchange.com/questions/331329/is-it-possible-to-compute-order-of-a-point-over-elliptic-curve
        # In the elliptic Curve cryptography, it is said that the order of base point
        # should be a prime number, and order of a point P is defined as k, where kP=O.

        # Theorem 9.2.1 The points on an elliptic curve together with O
        # have cyclic subgroups. Under certain conditions all points on an
        # elliptic curve form a cyclic group.
        # For this specific curve the group order is a prime and, according to Theo-
        # rem 8.2.4, every element is primitive.

        # Question: What is the order of our PE?
        # the order must be p, since p is a prime

        self.scalar = (self.private + self.mask) % self.q

        # If the scalar is less than two (2), the private and mask MUST be
        # thrown away and new values generated.  Once a valid scalar and
        # Element are generated, the mask is no longer needed and MUST be
        # irretrievably destroyed.
        if self.scalar < 2:
            raise ValueError('Scalar is {}, regenerating...'.format(self.scalar))

        P = self.curve.double_add_algorithm(self.mask, self.PE)

        # get the inverse of res
        # −P = (x_p , p − y_p ).
        self.element = self.curve.ec_inv(P)

        assert self.curve.valid(self.element)

        # The peers exchange their scalar and Element and check the peer's
        # scalar and Element, deemed peer-scalar and Peer-Element.  If the peer
        # has sent an identical scalar and Element -- i.e., if scalar equals
        # peer-scalar and Element equals Peer-Element -- it is sign of a
        # reflection attack, and the exchange MUST be aborted.  If the values
        # differ, peer-scalar and Peer-Element must be validated.

        logger.info('[{}] Sending scalar and element to the Peer!'.format(self.name))
        logger.info('[{}] Scalar={}'.format(self.name, self.scalar))
        logger.info('[{}] Element={}'.format(self.name, self.element))

        return self.scalar, self.element

    def compute_shared_secret(self, peer_element, peer_scalar, peer_mac):
        """
        ss = F(scalar-op(private,
                         element-op(peer-Element,
                                    scalar-op(peer-scalar, PE))))

        AP1: K = private(AP1) • (scal(AP2) • P(x, y) ◊ new_point(AP2))
               = private(AP1) • private(AP2) • P(x, y)
        AP2: K = private(AP2) • (scal(AP1) • P(x, y) ◊ new_point(AP1))
               = private(AP2) • private(AP1) • P(x, y)

        A shared secret element is computed using one’s rand and
        the other peer’s element and scalar:
        Alice: K = rand A • (scal B • PW + elemB )
        Bob: K = rand B • (scal A • PW + elemA )

        Since scal(APx) • P(x, y) is another point, the scalar multiplied point
        of e.g. scal(AP1) • P(x, y) is added to the new_point(AP2) and afterwards
        multiplied by private(AP1).
        """
        self.peer_element = peer_element
        self.peer_scalar = peer_scalar
        self.peer_mac = peer_mac

        assert self.curve.valid(self.peer_element)

        # If both the peer-scalar and Peer-Element are
        # valid, they are used with the Password Element to derive a shared
        # secret, ss:

        Z = self.curve.double_add_algorithm(self.peer_scalar, self.PE)
        ZZ = self.curve.ec_add(self.peer_element, Z)
        K = self.curve.double_add_algorithm(self.private, ZZ)

        self.k = K[0]

        logger.info('[{}] Shared Secret ss={}'.format(self.name, self.k))

        own_message = '{}{}{}{}{}{}'.format(self.k , self.scalar , self.peer_scalar , self.element[0] , self.peer_element[0] , self.mac_address).encode()

        H = hashlib.sha256()
        H.update(own_message)
        self.token = H.hexdigest()

        return self.token


#important
    def confirm_exchange(self, peer_token):
        """
            In the Confirm Exchange, both sides confirm that they derived the
            same secret, and therefore, are in possession of the same password.
        """
        peer_message = '{}{}{}{}{}{}'.format(self.k , self.peer_scalar , self.scalar , self.peer_element[0] , self.element[0] , self.peer_mac).encode()
        H = hashlib.sha256()
        H.update(peer_message)
        self.peer_token_computed = H.hexdigest()

        logger.info('[{}] Computed Token from Peer={}'.format(self.name, self.peer_token_computed))
        logger.info('[{}] Received Token from Peer={}'.format(self.name, peer_token))

        # Pairwise Master Key” (PMK)
        # compute PMK = H(k | scal(AP1) + scal(AP2) mod q)
        pmk_message = '{}{}'.format(self.k, (self.scalar + self.peer_scalar) % self.q).encode()
        
        #H = hashlib.sha256()
        #print ("H",  H)
        #H.update(pmk_message)

        self.PMK = hashlib.sha256(pmk_message).digest()

        logger.info('[{}] Pairwise Master Key(PMK)={}'.format(self.name, self.PMK))
        return self.PMK

    def key_derivation_function(self, n, base, seed):
        """
        B.5.1 Per-Message Secret Number Generation Using Extra Random Bits

        Key derivation function from Section B.5.1 of [FIPS186-4]

        The key derivation function, KDF, is used to produce a
        bitstream whose length is equal to the length of the prime from the
        group's domain parameter set plus the constant sixty-four (64) to
        derive a temporary value, and the temporary value is modularly
        reduced to produce a seed.
        """
        combined_seed = '{}{}'.format(base, seed).encode()

        # base and seed concatenated are the input to the RGB
        random.seed(combined_seed)

        # Obtain a string of N+64 returned_bits from an RBG with a security strength of
        # requested_security_strength or more.

        randbits = random.getrandbits(n)
        binary_repr = format(randbits, '0{}b'.format(n))

        assert len(binary_repr) == n

        logger.debug('Rand={}'.format(binary_repr))

        # Convert returned_bits to the non-negative integer c (see Appendix C.2.1).
        C = 0
        for i in range(n):
            if int(binary_repr[i]) == 1:
                C += pow(2, n-i)

        logger.debug('C={}'.format(C))

        #k = (C % (n - 1)) + 1

        k = C

        logger.debug('k={}'.format(k))

        return k

    def compute_hashed_password(self, counter):
        maxm = max(self.mac_address, self.other_mac)
        minm = min(self.mac_address, self.other_mac)
        message = '{}{}{}{}'.format(maxm, minm, self.password, counter).encode()
        logger.debug('Message to hash is: {}'.format(message))
        H = hashlib.sha256()
        H.update(message)
        digest = H.digest()
        return digest

#for encryption stuff
BLOCK_SIZE = 16
pad = lambda s: bytes(s + (BLOCK_SIZE - len(s) % BLOCK_SIZE) * chr(BLOCK_SIZE - len(s) % BLOCK_SIZE), 'utf-8')
unpad = lambda s: s[:-ord(s[-1:])]

'''
def encrypt(raw, thePMK):
    raw = pad(raw)
    iv = Random.new().read(AES.block_size)
    cipher = AES.new(thePMK, AES.MODE_CBC, iv)
    return base64.b64encode(iv + cipher.encrypt(raw))
'''

'''
def encrypt_file(key, in_filename):
    """ Encrypts a file using AES (CBC mode) with the
        given key.

        key:
            The encryption key - a string that must be
            either 16, 24 or 32 bytes long. Longer keys
            are more secure.

        in_filename:
            Name of the input file

        out_filename:
            If None, '<in_filename>.enc' will be used.

        chunksize:
            Sets the size of the chunk which the function
            uses to read and encrypt the file. Larger chunk
            sizes can be faster for some files and machines.
            chunksize must be divisible by 16.
    """
    chunksize=64*1024

    if not out_filename:
        #out_filename = in_filename + '.enc'
        out_filename = 'secret_out.enc'
    
    #iv = Random.new().read(AES.block_size)
    #iv = ''.join(chr(random.randint(0, 0xFF)) for i in range(16))
    iv = Random.new().read(16)

    encryptor = AES.new(key, AES.MODE_CBC, iv)
    filesize = os.path.getsize(in_filename)

    with open(in_filename, 'rb') as infile:
        with open(out_filename, 'wb') as outfile:
            outfile.write(struct.pack('<Q', filesize))
            outfile.write(iv)

            while True:
                chunk = infile.read(chunksize)
                if len(chunk) == 0:
                    break
                elif len(chunk) % 16 != 0:
                    chunk += ' ' * (16 - len(chunk) % 16)

                outfile.write(encryptor.encrypt(chunk))
'''

def encrypt(key, filename):
    chunksize = 64*1024
    outputFile = filename+".hacklab"
    filesize = str(os.path.getsize(filename)).zfill(16)
    IV = Random.new().read(16)

    encryptor = AES.new(key, AES.MODE_CBC, IV)

    with open(filename, 'rb') as infile:
	    with open(outputFile, 'wb') as outfile:
	    	outfile.write(filesize.encode('utf-8'))
	    	outfile.write(IV)

	    	while True:
	    		chunk = infile.read(chunksize)

	    		if len(chunk) == 0:
	    			break          

	    		elif len(chunk) % 16 != 0:
	    			chunk += b' ' * (16 - (len(chunk) % 16))

	    		outfile.write(encryptor.encrypt(chunk))
    
    return outputFile

''' 
def decrypt(enc, password):
    private_key = hashlib.sha256(password.encode("utf-8")).digest()
    enc = base64.b64decode(enc)
    iv = enc[:16]
    cipher = AES.new(private_key, AES.MODE_CBC, iv)
    return unpad(cipher.decrypt(enc[16:]))
'''

def decrypt(key, filename):
	chunksize = 64 * 1024
	outputFile = filename.split('.hacklab')[0]

	with open(filename, 'rb') as infile:
		filesize = int(infile.read(16))
		IV = infile.read(16)
		decryptor = AES.new(key, AES.MODE_CBC, IV)

		with open(outputFile, 'wb') as outfile:
			while True:
				chunk = infile.read(chunksize)

				if len(chunk) == 0:
					break

				outfile.write(decryptor.decrypt(chunk))
			outfile.truncate(filesize)

def handshake():

    start = time.time()
    
    #mac1, mac2 = '44:67:2D:2C:91:A6', '44:37:2C:2F:91:36'    
    my_mac = ':'.join(re.findall('..', '%012x' % uuid.getnode()))
    print (my_mac.encode())
    
    #sta = Peer('client', mac1, 'STA')
    ap = Peer('abc1238', my_mac, 'AP')

    logger.info('Starting hunting and pecking to derive PE...\n')
    
    
    sock.listen(1)
    conn, addr = sock.accept()
    with conn:
        print('Connected by', addr)
        #while True:
        other_mac = conn.recv(1024).decode()
        print (other_mac)
        conn.send(my_mac.encode())

        ap.initiate(other_mac)
            
        print() 
        logger.info('Starting dragonfly commit exchange...\n')
        scalar_ap, element_ap = ap.commit_exchange()

        #conn.sendall(str(scalar_ap).encode()) 
        #conn.sendall(str(element_ap).encode())
        conn.sendall(str.encode("\n".join([str(scalar_ap), str(element_ap)])))

        #scalar_element_ap = json.dumps({"a": scalar_ap, "b": element_ap})
        #sock.send(scalar_element_ap.encode())

        print()
        logger.info('Computing shared secret...\n')

        '''
        scalar_element_sta = sock.recv(1024)
        scalar_element_sta = json.loads(scalar_element_sta.decode())
        scalar_sta = int(scalar_element_sta.get("a"))
        element_sta = scalar_element_sta.get("b")
        '''
        #scalar_sta, element_sta = [int(i) for i in sock.recv(1024).decode('utf-8').split('\n')]

        scalar_element_ap = conn.recv(1024).decode()
        data = scalar_element_ap.split('\n')

        #scalar_sta = int(conn.recv(1024).decode())
        #element_sta = conn.recv(1024).decode()

        scalar_sta = data[0]
        element_sta = data[1]

        print (scalar_sta)
        print (element_sta)        
   
        print()
        print()

        namedtuple_element_sta = eval(element_sta)
        print(namedtuple_element_sta.y, namedtuple_element_sta.x)

        print()
        print()

        ap_token = ap.compute_shared_secret(namedtuple_element_sta, int(scalar_sta), other_mac)
        conn.send(ap_token.encode())

        print()
        logger.info('Confirm Exchange...\n')
        
        sta_token = conn.recv(1024).decode()
        PMK_key = ap.confirm_exchange(sta_token)
        
        dragonflyhandshake = time.time()

        print(PMK_key)
        
        #subprocess.call("./Adder_alice")
        unencrypted_cloudkey_filesize = os.path.getsize("cloud.key")
        
        #data will be replaced with either the public key or the public key
        
        print('encrypting cloud.key..........')
        cloud_key_file = "cloud.key"
        #output_file = "secret_out.enc"

        encryptHEkeystart = time.time()
        output_cloud_key_file = encrypt(PMK_key, cloud_key_file)
        encryptHEkeyend = time.time()

        #encrypted = encrypt("This is a cloud message", PMK_key)
        print("this file " , output_cloud_key_file,  " is encrypted \n ")
        print("the file size is \n ", os.path.getsize(output_cloud_key_file))
        
        sendHEkeystart = time.time()
        f = open(output_cloud_key_file,'rb') # Open in binary
        l = f.read(8192)
        print(l)
        while (l):
            conn.send(l)
            #print('Sent ',repr(l))
            l = f.read(8192)
        f.close()
        sendHEkeyend = time.time()
        
        print("\nthe initial file size is \n ", unencrypted_cloudkey_filesize)
        print("\nthe encrypted file size is \n ", os.path.getsize(output_cloud_key_file))
    
        conn.close()

        os.system("md5sum cloud.key")

        end = time.time()

        totalkeysendtime = end - start
        dragonflykeyauthtime = dragonflyhandshake - start
        encryptHEkeytime = encryptHEkeyend - encryptHEkeystart
        sendpubkeytime = sendHEkeyend - sendHEkeystart

        timelist = [totalkeysendtime, dragonflykeyauthtime, encryptHEkeytime, sendpubkeytime]

        keytimefile = "pubkeysendtime.csv"

        if os.path.isfile(keytimefile):
            print("Appending to file pubkeysendtime.csv")
            with open('pubkeysendtime.csv','a') as file:
                writer = csv.writer(file)
                writer.writerow(timelist)              
        else:
            print("Making new file pubkeysendtime.csv")
            with open('pubkeysendtime.csv','w') as file:
                fields=['totalkeysendtime','dragonflykeyauthtime','encryptHEkeytime','sendpubkeytime']
                writer = csv.writer(file)
                writer.writerow(fields)
                writer.writerow(timelist)

        print("recording time complete")

        print("\nTotal script run time: ", end - start)
        print("Dragonfly handshake time: ", dragonflyhandshake - start)
        print("Encrypting key time: ", encryptHEkeyend - encryptHEkeystart)
        print("Sending Pub Key time: ", sendHEkeyend - sendHEkeystart)

'''
def tests():
    """
    Test the fucking Curve class.

    See Understanding Cryptography ECC Section.
    """
    a, b, p = 2, 2, 17
    curve = Curve(a, b, p)

    P = Point(5, 1)
    assert curve.double_add_algorithm(19, P) == O

    T = P
    for i in range(p+1):
        T = curve.ec_add(T, P)

    assert curve.double_add_algorithm(19, P) == T
'''

if __name__ == '__main__':
    #tests()
    handshake()