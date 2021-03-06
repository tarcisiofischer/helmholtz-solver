from callbacks import dispatch_callbacks
from complex_linear_system import (
    convert_complex_linear_system_to_real,
    extract_complex_solution,
)
import numpy as np
from scipy.sparse.coo import coo_matrix
from numpy.linalg.linalg import det
import pypardiso
import _fwi_ls
import globals as g


def solve_2d_hellmholtz(
    mesh, omega, callbacks=None,
):
    if callbacks is None:
        callbacks = {}

    Ke, f = convert_complex_linear_system_to_real(*_prepare_linear_system(mesh, omega))
    P = extract_complex_solution(_solve_linear_system(Ke, f))

    dispatch_callbacks(callbacks, "on_after_solve_2d_hellmholtz", P=P, mesh=mesh)


def _solve_linear_system(A, b):
    return pypardiso.spsolve(A.tocsc(), b)


def _build_local_Ke(element_points, omega, mu, eta):
    integration_point = np.array(
        [
            [-1.0 / np.sqrt(3.0), -1.0 / np.sqrt(3.0)],
            [+1.0 / np.sqrt(3.0), -1.0 / np.sqrt(3.0)],
            [+1.0 / np.sqrt(3.0), +1.0 / np.sqrt(3.0)],
            [-1.0 / np.sqrt(3.0), +1.0 / np.sqrt(3.0)],
        ]
    )

    w = np.array([1.0, 1.0, 1.0, 1.0])

    N = np.zeros(shape=(1, 4))
    M_hat = np.zeros(shape=(4, 4))
    C_hat = np.zeros(shape=(4, 4), dtype=np.complex)
    K_hat = np.zeros(shape=(4, 4))
    for i in range(4):
        r, s = integration_point[i]

        N[0, 0] = (1.0 - r) * (1.0 - s) / 4.0
        N[0, 1] = (1.0 + r) * (1.0 - s) / 4.0
        N[0, 2] = (1.0 + r) * (1.0 + s) / 4.0
        N[0, 3] = (1.0 - r) * (1.0 + s) / 4.0

        grad_N = np.array(
            [
                [-(1.0 - s) / 4.0, -(1.0 - r) / 4.0],
                [+(1.0 - s) / 4.0, -(1.0 + r) / 4.0],
                [+(1.0 + s) / 4.0, +(1.0 + r) / 4.0],
                [-(1.0 + s) / 4.0, +(1.0 - r) / 4.0],
            ]
        )

        J = np.dot(grad_N.T, element_points)
        dJ = det(J)

        inv_J = np.array([[J[1, 1], -J[0, 1]], [-J[1, 0], J[0, 0]],])
        B = (1.0 / dJ) * np.dot(inv_J, grad_N.T)

        M_hat += w[i] * -(omega ** 2.0) * mu * np.dot(N.T, N) * dJ
        C_hat += w[i] * 1j * omega * eta * np.dot(N.T, N) * dJ
        K_hat += w[i] * np.dot(B.T, B) * dJ
    K = M_hat + C_hat + K_hat
    return K


def _assembly_K(mesh, omega):
    build_local_Ke = g.choose_impl(_fwi_ls.build_local_Ke, _build_local_Ke)

    # Prepare Ke for each element, and keep their data to be used in the assembly
    Ke_local_list = []
    for connectivity, points, mu, eta in zip(
        mesh.connectivity_list, mesh.points_in_elements, mesh.mu, mesh.eta
    ):
        Ke_local_list.append((connectivity, build_local_Ke(points, omega, mu, eta)))

    # Assembly the global matrix
    Ke_coo_i = []
    Ke_coo_j = []
    Ke_coo_data = []
    for connectivity, Ke_local in Ke_local_list:
        for k, p1 in enumerate(connectivity):
            for l, p2 in enumerate(connectivity):
                Ke_coo_i.append(p1)
                Ke_coo_j.append(p2)
                Ke_coo_data.append(Ke_local[k, l])

    # Build the sparse data structure
    Ke_global = coo_matrix(
        (Ke_coo_data, (Ke_coo_i, Ke_coo_j)),
        shape=(mesh.n_points, mesh.n_points),
        dtype=np.complex,
    )

    return Ke_global


def _build_local_f(element_points, S_e):
    integration_point = np.array(
        [
            [-1.0 / np.sqrt(3.0), -1.0 / np.sqrt(3.0)],
            [+1.0 / np.sqrt(3.0), -1.0 / np.sqrt(3.0)],
            [+1.0 / np.sqrt(3.0), +1.0 / np.sqrt(3.0)],
            [-1.0 / np.sqrt(3.0), +1.0 / np.sqrt(3.0)],
        ]
    )

    w = np.array([1.0, 1.0, 1.0, 1.0])

    N = np.zeros(shape=(1, 4))
    f = np.zeros(shape=(4, 1))
    for i in range(4):
        r, s = integration_point[i]

        N[0, 0] = (1.0 - r) * (1.0 - s) / 4.0
        N[0, 1] = (1.0 + r) * (1.0 - s) / 4.0
        N[0, 2] = (1.0 + r) * (1.0 + s) / 4.0
        N[0, 3] = (1.0 - r) * (1.0 + s) / 4.0

        grad_N = np.array(
            [
                [-(1.0 - s) / 4.0, -(1.0 - r) / 4.0],
                [+(1.0 - s) / 4.0, -(1.0 + r) / 4.0],
                [+(1.0 + s) / 4.0, +(1.0 + r) / 4.0],
                [-(1.0 + s) / 4.0, +(1.0 - r) / 4.0],
            ]
        )
        J = np.dot(grad_N.T, element_points)
        dJ = det(J)

        f += w[i] * N.T * S_e * dJ

    return f


def _assembly_f(mesh):
    build_local_f = g.choose_impl(_fwi_ls.build_local_f, _build_local_f)

    f = np.zeros(shape=(mesh.n_points, 1))
    for eid, (connectivity, points) in enumerate(
        zip(mesh.connectivity_list, mesh.points_in_elements)
    ):
        f_local = build_local_f(points, mesh.source_at_element(eid)).reshape(4, 1)
        for k, p in enumerate(connectivity):
            f[p, 0] += f_local[k, 0]
    return f


def _prepare_linear_system(mesh, omega):
    return _assembly_K(mesh, omega), _assembly_f(mesh)
