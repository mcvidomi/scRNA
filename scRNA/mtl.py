import numpy as np
from sklearn import decomposition as decomp
import sklearn.metrics as metrics
import scipy.stats as stats

from sc3_pipeline_impl import cell_filter, gene_filter, data_transformation_log2, distances
from utils import load_dataset_tsv


def gene_names_conversion():
    """
    :return: a dictionary for gene ids
    """
    import utils
    mypath = utils.__file__
    mypath = mypath.rsplit('/', 1)[0]
    # print mypath
    gene_names = np.loadtxt('{0}/gene_names.txt'.format(mypath), skiprows=1, dtype='object')
    gene_id_map = dict()
    for i in range(gene_names.shape[0]):
        gene_id_map[gene_names[i, 0]] = gene_names[i, 1]
    return gene_id_map


def filter_and_sort_genes(gene_ids1, gene_ids2):
    """
    Remove genes from either list that do not appear in the other. Sort the indices.
    :param gene_ids1: list of gene names
    :param gene_ids2: list of gene names
    :return: (same-size) lists of indices
    """
    gene_id_map = gene_names_conversion(gene_ids1, gene_ids2)
    inds1 = []
    inds2 = []
    for i in range(gene_ids1.size):
        id = gene_ids1[i]
        if gene_id_map.has_key(id):
            ens_id = gene_id_map[id]
            ind = np.where(gene_ids2 == ens_id)[0]
            if ind.size == 1:
                # exactly 1 id found
                inds1.append(i)
                inds2.append(ind[0])
    return np.array(inds1, dtype=np.int), np.array(inds2, dtype=np.int)


def nmf_mtl_full(data, gene_ids, fmtl=None, fmtl_geneids=None,
                 nmf_k=10, nmf_alpha=1.0, nmf_l1=0.75,
                 data_transf_fun=None, cell_filter_fun=None, gene_filter_fun=None,
                 max_iter=5000, rel_err=1e-6):
    """
    Multitask SC3 distance function + Pre-processing.
    :param data: Target dataset (trg-genes x trg-cells)
    :param gene_ids: Target gene ids
    :param fmtl: Filename of the scRNA source dataset (src-genes x src-cells)
    :param fmtl_geneids: Filename for corresponding source gene ids
    :param nmf_k: Number of latent components (cluster)
    :param nmf_alpha: Regularization influence
    :param nmf_l1: [0,1] strength of l1-regularizer within regularization
    :param data_transf_fun: Source data transformation function (e.g. log2+1 transfor, or None)
    :param cell_filter_fun: Source cell filter function
    :param gene_filter_fun: Source gene filter function
    :param max_iter: maximum number of iterations for target nmf
    :param rel_err: maximum relative error before target nmf stops
    :return: Distance matrix trg-cells x trg-cells
    """
    pdata, pgene_ids, labels = load_dataset_tsv(fmtl, fgenes=fmtl_geneids)
    num_transcripts, num_cells = pdata.shape

    # filter cells
    remain_cell_inds = np.arange(0, num_cells)
    res = cell_filter_fun(pdata)
    remain_cell_inds = np.intersect1d(remain_cell_inds, res)
    A = pdata[:, remain_cell_inds]

    # filter genes
    remain_inds = np.arange(0, num_transcripts)
    res = gene_filter_fun(A)
    remain_inds = np.intersect1d(remain_inds, res)

    # transform data
    X = A[remain_inds, :]
    X = data_transf_fun(X)
    pgene_ids = pgene_ids[remain_inds]

    # find (and translate) a common set of genes
    # inds1, inds2 = filter_and_sort_genes(gene_ids, pgene_ids)

    # expect identifiers to be unique
    print np.unique(pgene_ids).shape, pgene_ids.shape
    print np.unique(gene_ids).shape, gene_ids.shape

    print np.unique(gene_ids)
    print np.intersect1d(pgene_ids, np.unique(pgene_ids))

    if not np.unique(pgene_ids).shape[0] == pgene_ids.shape[0]:
        # raise Exception('(MTL) Gene ids are supposed to be unique.')
        print('Warning! (MTL gene ids) Gene ids are supposed to be unique. '
              'Only {0} of {1}  entries are unique.'.format(np.unique(pgene_ids).shape[0], pgene_ids.shape[0]))
        print('Only first occurance will be used.')
    if not np.unique(gene_ids).shape[0] == gene_ids.shape[0]:
        # raise Exception('(Target) Gene ids are supposed to be unique.')
        print('Warning! (Target gene ids) Gene ids are supposed to be unique. '
              'Only {0} of {1}  entries are unique.'.format(np.unique(gene_ids).shape[0], gene_ids.shape[0]))
        print('Only first occurance will be used.')

    common_ids = np.intersect1d(gene_ids, pgene_ids)
    print('Both datasets have (after processing) {0} gene ids in common.'.format(common_ids.shape[0]))

    # find indices of common_ids in pgene_ids and gene_ids
    inds1 = np.zeros(common_ids.shape[0], dtype=np.int)
    inds2 = np.zeros(common_ids.shape[0], dtype=np.int)
    for i in range(common_ids.shape[0]):
        inds1[i] = np.argwhere(common_ids[i] == gene_ids)[0]
        inds2[i] = np.argwhere(common_ids[i] == pgene_ids)[0]

    print 'MTL source {0} genes -> {1} genes.'.format(pgene_ids.size, inds2.size)
    print 'MTL target {0} genes -> {1} genes.'.format(gene_ids.size, inds1.size)

    W, H, H2, Hsrc, reject = mtl_nmf(X[inds2, :], data[inds1, :],
                                     nmf_k=nmf_k, nmf_alpha=nmf_alpha, nmf_l1=nmf_l1,
                                     max_iter=max_iter, rel_err=rel_err)
    src_gene_inds = inds2
    trg_gene_inds = inds1
    return W, H, H2, Hsrc, reject, src_gene_inds, trg_gene_inds


def mtl_distance(data, gene_ids, fmtl=None, fmtl_geneids=None, metric='euclidean',
                 mixture=0.75, nmf_k=10, nmf_alpha=1.0, nmf_l1=0.75,
                 data_transf_fun=None, cell_filter_fun=None, gene_filter_fun=None):
    """
    Multitask SC3 distance function.
    :param data: Target dataset (trg-genes x trg-cells)
    :param gene_ids: Target gene ids
    :param fmtl: Filename of the scRNA source dataset (src-genes x src-cells)
    :param fmtl_geneids: Filename for corresponding source gene ids
    :param metric: Which metric should be applied.
    :param mixture: [0,1] Convex combination of target only distance and mtl distance (0: no mtl influence)
    :param nmf_k: Number of latent components (cluster)
    :param nmf_alpha: Regularization influence
    :param nmf_l1: [0,1] strength of l1-regularizer within regularization
    :param data_transf_fun: Source data transformation function (e.g. log2+1 transfor, or None)
    :param cell_filter_fun: Source cell filter function
    :param gene_filter_fun: Source gene filter function
    :return: Distance matrix trg-cells x trg-cells
    """
    W, H, H2, Hsrc, reject, src_gene_inds, trg_gene_inds = nmf_mtl_full(
        data, gene_ids, fmtl=fmtl, fmtl_geneids=fmtl_geneids,
        nmf_k=nmf_k, nmf_alpha=nmf_alpha, nmf_l1=nmf_l1,
        data_transf_fun=data_transf_fun, cell_filter_fun=cell_filter_fun, gene_filter_fun=gene_filter_fun)

    # convex combination of vanilla distance and nmf distance
    dist1 = distances(data, [], metric=metric)
    dist2 = distances(W.dot(H2), [], metric=metric)
    # normalize distance
    if np.max(dist2) < 1e-10:
        if mixture == 1.0:
            raise Exception('Distances are all zero and mixture=1.0. Seems that source and target'
                            ' data do not go well together.')
        else:
            print 'Warning! Max distance is 0.0.'
    else:
        print 'Max dists before normalization: ', np.max(dist1), np.max(dist2)
        dist2 *= np.max(dist1) / np.max(dist2)
    return mixture*dist2 + (1.-mixture)*dist1


def mtl_nmf(Xsrc, Xtrg, nmf_k=10, nmf_alpha=1.0, nmf_l1=0.75, max_iter=5000, rel_err=1e-6):
    """
    Multitask clustering. The source dataset 'Xsrc' is clustered using NMF. Resulting
    dictionary 'W' is then used to reconstruct 'Xtrg'
    :param Xsrc: genes x src_cells matrix
    :param Xtrg: genes x trg_cells matrix
    :param nmf_k: number of latent components (cluster)
    :param nmf_alpha: regularization influence
    :param nmf_l1: [0,1] strength of influence of l1-regularizer within regularization
    :param max_iter: max number of iterations for trg-matrix fit
    :param rel_err: threshold for reconstruction error decrease before stopping
    :return: dictionary W (genes x nmf_k), trg-data matrix H (nmf_k x trg-cells), trg-data matrix H2,
    and src-data matrix (nmf_k x src-cells) and list of reject measures per trg-cell
    """
    nmf = decomp.NMF(alpha=nmf_alpha, init='nndsvdar', l1_ratio=nmf_l1, max_iter=1000,
        n_components=nmf_k, random_state=0, shuffle=True, solver='cd', tol=0.00001, verbose=0)
    W = nmf.fit_transform(Xsrc)
    Hsrc = nmf.components_

    # check solution: if regularizer is too strong this can result in 'NaN's
    if np.any(np.isnan(W)):
        raise Exception('W contains NaNs (alpha={0}, k={1}, l1={2}, data={3}x{4}'.format(
            nmf_alpha, nmf_k, nmf_l1, Xsrc.shape[0], Xsrc.shape[1]))
    if np.any(np.isnan(Hsrc)):
        raise Exception('Hsrc contains NaNs (alpha={0}, k={1}, l1={2}, data={3}x{4}'.format(
            nmf_alpha, nmf_k, nmf_l1, Xsrc.shape[0], Xsrc.shape[1]))

    H = np.random.randn(nmf_k, Xtrg.shape[1])
    a1, a2 = np.where(H < 0.)
    H[a1, a2] *= -1.
    n_iter = 0
    err = 1e10
    while n_iter < max_iter:
        n_iter += 1
        H *= W.T.dot(Xtrg) / W.T.dot(W.dot(H))
        new_err = np.sum(np.abs(Xtrg - W.dot(H)))/np.float(Xtrg.size)  # absolute
        # new_err = np.sqrt(np.sum((Xtrg - W.dot(H))*(Xtrg - W.dot(H)))) / np.float(Xtrg.size)  # frobenius
        if np.abs((err - new_err) / err) <= rel_err and err > new_err:
            break
        err = new_err
    print '  Number of iterations for reconstruction     : ', n_iter
    print '  Elementwise absolute reconstruction error   : ', np.sum(np.abs(Xtrg - W.dot(H))) / np.float(Xtrg.size)
    print '  Fro-norm reconstruction error               : ', np.sqrt(np.sum((Xtrg - W.dot(H))*(Xtrg - W.dot(H)))) / np.float(Xtrg.size)

    if np.any(np.isnan(H)):
        raise Exception('Htrg contains NaNs (alpha={0}, k={1}, l1={2}, data={3}x{4}'.format(
            nmf_alpha, nmf_k, nmf_l1, Xsrc.shape[0], Xsrc.shape[1]))

    H2 = np.zeros((nmf_k, Xtrg.shape[1]))
    H2[(np.argmax(H, axis=0), np.arange(Xtrg.shape[1]))] = 1
    # H2[ (np.argmax(H, axis=0), np.arange(Xtrg.shape[1])) ] = np.sum(H, axis=0)

    print '  H2 Elementwise absolute reconstruction error: ', np.sum(np.abs(Xtrg - W.dot(H2))) / np.float(Xtrg.size)
    print '  H2 Fro-norm reconstruction error            : ', np.sqrt(np.sum((Xtrg - W.dot(H2))*(Xtrg - W.dot(H2)))) / np.float(Xtrg.size)

    kurts = stats.kurtosis(H, fisher=False, axis=0)
    K1 = Xtrg.T.dot(Xtrg)
    K2 = W.dot(H).T.dot(W.dot(H))
    K3 = W.dot(H2).T.dot(W.dot(H2))

    def classifier(K, kurts):
        from utils import kta_align_binary, normalize_kernel, center_kernel
        sinds = np.argsort(kurts)
        K = center_kernel(K)
        K = normalize_kernel(K)
        max_kta = -1.0
        max_kta_ind = -1
        for i in range(Xtrg.shape[1]-2):
            # 1. build binary label matrix
            labels = np.ones(kurts.size, dtype=np.int)
            labels[sinds[:i+1]] = -1
            kta = kta_align_binary(K, labels)
            if kta > max_kta:
                max_kta = kta
                max_kta_ind = i+1

        labels = np.ones(kurts.size, dtype=np.int)
        labels[sinds[:max_kta_ind]] = -1
        return labels

    reject = list()
    reject.append(('kurtosis', stats.kurtosis(H, fisher=False, axis=0)))
    reject.append(('KTA kurt1', classifier(K1, kurts)))
    reject.append(('KTA kurt2', classifier(K2, kurts)))
    reject.append(('KTA kurt3', classifier(K3, kurts)))
    reject.append(('Dist L2 H', -np.sum( (np.abs(Xtrg - W.dot(H))**2. ), axis=0)))
    reject.append(('Dist L2 H2', -np.sum( (np.abs(Xtrg - W.dot(H2))**2. ), axis=0)))
    reject.append(('Dist L1 H', -np.sum( np.abs(Xtrg - W.dot(H)), axis=0)))
    reject.append(('Dist L1 H2', -np.sum( np.abs(Xtrg - W.dot(H2)), axis=0)))
    return W, H, H2, Hsrc, reject


def mtl_toy_distance(data, gene_ids, src_data, src_labels=None, trg_labels=None,
                     metric='euclidean', mixture=0.75, nmf_k=4, nmf_alpha=1.0, nmf_l1=0.75):
    """
    Multitask SC3 distance function for toy data (i.e. no transformation, no gene id matching).
    :param data:
    :param gene_ids: (not used)
    :param src_data:
    :param src_labels: (optional)
    :param trg_labels: (optional)
    :param metric: Which metric should be applied.
    :param mixture: [0,1] Convex combination of target only distance and mtl distance (0: no mtl influence)
    :param nmf_k: Number of latent components (cluster)
    :param nmf_alpha: strength of regularization
    :param nmf_l1: [0,1] influence of L1-regularizer within regularization
    :return: trg-cells x trg-cells distance matrix
    """
    if mixture == 0.0:
        print('No MTL used (mixture={0})'.format(mixture))
        return distances(data, [], metric=metric)

    W, H, H2, Hsrc, _ = mtl_nmf(src_data, data, nmf_k=nmf_k, nmf_alpha=nmf_alpha, nmf_l1=nmf_l1)

    if src_labels is not None:
        print 'Labels in src: ', np.unique(src_labels)
        print 'ARI: ', metrics.adjusted_rand_score(src_labels, np.argmax(Hsrc, axis=0))
    if trg_labels is not None:
        print 'Labels in trg: ', np.unique(trg_labels)
        print 'ARI: ', metrics.adjusted_rand_score(trg_labels, np.argmax(H, axis=0))

    # convex combination of vanilla distance and nmf distance
    dist1 = distances(data, [], metric=metric)
    dist2 = distances(W.dot(H2), [], metric=metric)
    # normalize distance

    if np.max(dist2) < 1e-10:
        if mixture == 1.0:
            print 'Warning! Max distance is 0.0 and mixture=1.0: reducing mixture to 0.9.'
            mixture = 0.9
            # raise Exception('Distances are all zero and mixture=1.0. Seems that source and target'
            #                 ' data do not go well together.')
        else:
            print 'Warning! Max distance is 0.0.'
    else:
        print 'Max dists before normalization: ', np.max(dist1), np.max(dist2)
        dist2 *= np.max(dist1) / np.max(dist2)

    print 'Max dists after normalization: ', np.max(dist1), np.max(dist2)
    fdist = mixture*dist2 + (1.-mixture)*dist1
    print mixture
    if np.any(fdist < 0.0):
        raise Exception('Final distance matrix contains negative values.')
    if np.any(np.isnan(fdist)):
        raise Exception('Final distance matrix contains NaNs.')
    if np.any(np.isinf(fdist)):
        raise Exception('Final distance matrix contains Infs.')
    return fdist