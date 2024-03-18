/*============================================================================
 * User functions for input of calculation parameters.
 *============================================================================*/

/* VERS */

/*
  This file is part of code_saturne, a general-purpose CFD tool.

  Copyright (C) 1998-2023 EDF S.A.

  This program is free software; you can redistribute it and/or modify it under
  the terms of the GNU General Public License as published by the Free Software
  Foundation; either version 2 of the License, or (at your option) any later
  version.

  This program is distributed in the hope that it will be useful, but WITHOUT
  ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
  FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
  details.

  You should have received a copy of the GNU General Public License along with
  this program; if not, write to the Free Software Foundation, Inc., 51 Franklin
  Street, Fifth Floor, Boston, MA 02110-1301, USA.
*/

/*----------------------------------------------------------------------------*/

#include "cs_defs.h"

/*----------------------------------------------------------------------------
 * Standard C library headers
 *----------------------------------------------------------------------------*/

#include <assert.h>
#include <math.h>
#include <string.h>
#include <stdio.h>

#if defined(HAVE_MPI)
#include <mpi.h>
#endif

#if defined(HAVE_HYPRE)
#include <HYPRE_krylov.h>
#include <HYPRE_parcsr_ls.h>
#include <HYPRE_utilities.h>
#endif

/*----------------------------------------------------------------------------
 * PLE library headers
 *----------------------------------------------------------------------------*/

#include <ple_coupling.h>

/*----------------------------------------------------------------------------
 * Local headers
 *----------------------------------------------------------------------------*/

#include "cs_headers.h"

#if defined(HAVE_PETSC)
#include "cs_sles_petsc.h"
#endif

/*----------------------------------------------------------------------------*/

BEGIN_C_DECLS

/*----------------------------------------------------------------------------*/
/*!
 * \file cs_user_parameters-linear_solvers.c
 *
 * \brief Linear solvers examples.
 *
 * See \ref parameters for examples.
 */
/*----------------------------------------------------------------------------*/

/*============================================================================
 * User function definitions
 *============================================================================*/

/*----------------------------------------------------------------------------*/
/*!
 * \brief Select physical model options, including user fields.
 *
 * This function is called at the earliest stages of the data setup,
 * so field ids are not available yet.
 */
/*----------------------------------------------------------------------------*/

#pragma weak cs_user_model
void
cs_user_model(void)
{

}

/*----------------------------------------------------------------------------*/
/*!
 * \brief Define or modify general numerical and physical user parameters.
 *
 * At the calling point of this function, most model-related most variables
 * and other fields have been defined, so specific settings related to those
 * fields may be set here.
 *
 * At this stage, the mesh is not built or read yet, so associated data
 * such as field values are not accessible yet, though pending mesh
 * operations and some fields may have been defined.
 *
 * \param[in, out]   domain    pointer to a cs_domain_t structure
 */
/*----------------------------------------------------------------------------*/

#pragma weak cs_user_parameters
void
cs_user_parameters(cs_domain_t   *domain)
{
  CS_NO_WARN_IF_UNUSED(domain);
}

/*----------------------------------------------------------------------------*/
/*!
 * \brief Define linear solver options.
 *
 * This function is called at the setup stage, once user and most model-based
 * fields are defined.
 *
 * Available native iterative linear solvers include conjugate gradient,
 * Jacobi, BiCGStab, BiCGStab2, and GMRES. For symmetric linear systems,
 * an algebraic multigrid solver is available (and recommended).
 *
 * External solvers may also be setup using this function, the cs_sles_t
 * mechanism allowing such through user-define functions.
 */
/*----------------------------------------------------------------------------*/

void
cs_user_linear_solvers(void)
{
  /* Settings to try:

  CS_SLES_P_SYM_GAUSS_SEIDEL as coarse level solver;
  in this case, also set n_max_iter_coarse_solver to 1 instead of 500.

  Also experiment with multigrid merging
  (activate cs_multigrid_set_merge_options). */

  /* Conjugate gradient preconditioned by multigrid for pressure */
  /*-------------------------------------------------------------*/

  {
    cs_sles_it_t *c = cs_sles_it_define(CS_F_(p)->id,
                                        NULL,
                                        CS_SLES_FCG,
                                        -1,
                                        10000);
    cs_sles_pc_t *pc = cs_multigrid_pc_create(CS_MULTIGRID_V_CYCLE);
    cs_multigrid_t *mg = cs_sles_pc_get_context(pc);
    cs_sles_it_transfer_pc(c, &pc);

    assert(strcmp(cs_sles_pc_get_type(cs_sles_it_get_pc(c)), "multigrid") == 0);

    cs_multigrid_set_solver_options
      (mg,
       CS_SLES_P_SYM_GAUSS_SEIDEL, /* descent smoother (CS_SLES_P_SYM_GAUSS_SEIDEL) */
       CS_SLES_P_SYM_GAUSS_SEIDEL, /* ascent smoother (CS_SLES_P_SYM_GAUSS_SEIDEL) */
       CS_SLES_PCG,            /* coarse solver (CS_SLES_P_GAUSS_SEIDEL) */
       1,              /* n max cycles (default 1) */
       1,              /* n max iter for descent (default 1) */
       1,              /* n max iter for asscent (default 1) */
       167,            /* n max iter coarse solver (default 1) */
       0,              /* polynomial precond. degree descent (default) */
       0,              /* polynomial precond. degree ascent (default) */
       0,              /* polynomial precond. degree coarse (default 0) */
       -1.0,           /* precision multiplier descent (< 0 forces max iters) */
       -1.0,           /* precision multiplier ascent (< 0 forces max iters) */
       1.0);           /* requested precision multiplier coarse (default 1) */


    /* Try increasing merge_stride; tested at 1 (default), 2, 4 mostly */

    int merge_stride = 1;

    cs_multigrid_set_merge_options(mg,
                                   merge_stride,   /* # of ranks merged at a time */
                                   1000,  /* mean # of cells under which we merge */
                                   500); /* global # of cells under which we merge */


    /* Try increasing min_g_cells to avoid solving a too small (latency-dominated)
       solver; though this might increase the total number of cycles or
       iterations required for convergence. */

    cs_multigrid_set_coarsening_options(mg,
                                        3,     /* aggregation_limit*/
                                        CS_GRID_COARSENING_DEFAULT,
                                        25,    /* n_max_levels */
                                        300,    /* min_g_cells */
                                        0.95,  /* P0P1 relaxation */
                                        0);    /* postprocess */

  }

#if defined(HAVE_HYPRE)

  /* Setting pressure solver with hypre with Default PCG+BoomerAMG options */
  /*-----------------------------------------------------------------------*/

  if (false) {
    cs_sles_hypre_define(CS_F_(p)->id,
                         NULL,
                         CS_SLES_HYPRE_PCG,            /* solver type */
                         CS_SLES_HYPRE_BOOMERAMG,      /* preconditioner type */
                         NULL,
                         NULL);
  }

#endif /* defined(HAVE_HYPRE) */
}
/*----------------------------------------------------------------------------*/
/*!
 * \brief Define time moments.
 *
 * This function is called at the setup stage, once user and most model-based
 * fields are defined, and before fine control of field output options
 * is defined.
 */
/*----------------------------------------------------------------------------*/

#pragma weak cs_user_time_moments
void
cs_user_time_moments(void)
{

}

/*----------------------------------------------------------------------------*/
/*!
 * \brief Define internal coupling options.
 *
 * Options are usually defined using cs_internal_coupling_add_entity.
 */
/*----------------------------------------------------------------------------*/

#pragma weak cs_user_internal_coupling
void
cs_user_internal_coupling(void)
{

}

/*----------------------------------------------------------------------------*/
/*!
 * \brief Define or modify output user parameters.
 *
 * For CDO schemes, this function concludes the setup of properties,
 * equations, source terms...
 *
 * \param[in, out]   domain    pointer to a cs_domain_t structure
 */
/*----------------------------------------------------------------------------*/

#pragma weak cs_user_finalize_setup
void
cs_user_finalize_setup(cs_domain_t   *domain)
{
  CS_UNUSED(domain);
}

/*----------------------------------------------------------------------------*/

END_C_DECLS

