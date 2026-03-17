#!/usr/bin/env Rscript

suppressPackageStartupMessages(library(BoolNet))

print_usage <- function() {
  cat(
    "Usage:\n",
    "  Rscript generate_traces_from_bnet.R --bnet <file.bnet> --config <traces_configuration.txt>\n\n",
    "Required args:\n",
    "  --bnet    Path to input .bnet file\n",
    "  --config  Path to traces configuration file (key = value)\n",
    sep = ""
  )
}

parse_args <- function(args) {
  if (length(args) == 0 || any(args %in% c("-h", "--help"))) {
    print_usage()
    quit(status = 0)
  }

  out <- list()
  i <- 1
  while (i <= length(args)) {
    key <- args[[i]]
    if (!startsWith(key, "--")) {
      stop(sprintf("Unexpected argument: %s", key))
    }
    if (i == length(args)) {
      stop(sprintf("Missing value for argument: %s", key))
    }
    value <- args[[i + 1]]
    out[[substring(key, 3)]] <- value
    i <- i + 2
  }
  out
}

read_kv_config <- function(path) {
  if (!file.exists(path)) {
    stop(sprintf("Config file not found: %s", path))
  }

  lines <- readLines(path, warn = FALSE)
  cfg <- list()

  for (idx in seq_along(lines)) {
    raw <- lines[[idx]]
    line <- trimws(sub("#.*$", "", raw))
    if (line == "") next

    if (!grepl("=", line, fixed = TRUE)) {
      stop(sprintf("Invalid config line %d in %s (expected key = value): %s", idx, path, raw))
    }

    parts <- strsplit(line, "=", fixed = TRUE)[[1]]
    key <- trimws(parts[[1]])
    value <- trimws(paste(parts[-1], collapse = "="))

    if (key == "" || value == "") {
      stop(sprintf("Invalid config line %d in %s: %s", idx, path, raw))
    }

    cfg[[key]] <- value
  }

  cfg
}

cfg_has <- function(cfg, key) {
  !is.null(cfg[[key]])
}

cfg_get <- function(cfg, keys, default = NULL) {
  for (k in keys) {
    if (cfg_has(cfg, k)) return(cfg[[k]])
  }
  default
}

cfg_get_int <- function(cfg, keys, default = NULL) {
  value <- cfg_get(cfg, keys, default)
  if (is.null(value)) return(NULL)
  out <- suppressWarnings(as.integer(value))
  if (is.na(out)) {
    stop(sprintf("Expected integer for config key(s): %s", paste(keys, collapse = ", ")))
  }
  out
}

cfg_get_num <- function(cfg, keys, default = NULL) {
  value <- cfg_get(cfg, keys, default)
  if (is.null(value)) return(NULL)
  out <- suppressWarnings(as.numeric(value))
  if (is.na(out)) {
    stop(sprintf("Expected numeric for config key(s): %s", paste(keys, collapse = ", ")))
  }
  out
}

cfg_get_bool <- function(cfg, keys, default = FALSE) {
  value <- cfg_get(cfg, keys, NULL)
  if (is.null(value)) return(default)
  normalized <- tolower(trimws(value))
  if (normalized %in% c("true", "t", "yes", "y", "1")) return(TRUE)
  if (normalized %in% c("false", "f", "no", "n", "0")) return(FALSE)
  stop(sprintf("Expected boolean for config key(s): %s", paste(keys, collapse = ", ")))
}

ensure_dir <- function(path) {
  if (!dir.exists(path)) {
    dir.create(path, recursive = TRUE)
  }
}

write_traces <- function(time_series, genes, out_dir, prefix, suffix, write_header) {
  ensure_dir(out_dir)

  for (i in seq_along(time_series)) {
    m <- t(time_series[[i]])  # time x genes
    fname <- file.path(out_dir, sprintf("%s%d%s", prefix, i, suffix))
    con <- file(fname, open = "wt")

    if (write_header) {
      writeLines(">trajectory", con)
    }

    write.table(
      m,
      file = con,
      sep = "\t",
      row.names = FALSE,
      col.names = FALSE,
      quote = FALSE
    )

    close(con)
    cat("Wrote trace:", fname, "\n")
  }
}

write_text_dump <- function(path, object, label = NULL) {
  lines <- capture.output({
    if (!is.null(label)) cat(label, "\n")
    print(object)
  })
  writeLines(lines, path)
  cat("Wrote:", path, "\n")
}

extract_fixed_points_rows <- function(attractor_obj, gene_names) {
  fixed_rows <- list()

  if (is.null(attractor_obj$attractors)) {
    return(fixed_rows)
  }

  for (att in attractor_obj$attractors) {
    cycle_length <- NA_integer_
    if (!is.null(att$cycleLength)) cycle_length <- suppressWarnings(as.integer(att$cycleLength))
    if (is.na(cycle_length)) {
      if (!is.null(att$involvedStates) && is.matrix(att$involvedStates)) {
        cycle_length <- ncol(att$involvedStates)
      } else {
        next
      }
    }
    if (cycle_length != 1) next

    state_matrix <- NULL
    if (!is.null(att$involvedStates) && is.matrix(att$involvedStates)) {
      state_matrix <- att$involvedStates
    } else if (!is.null(att$stateInfo) && is.matrix(att$stateInfo)) {
      state_matrix <- att$stateInfo
    }
    if (is.null(state_matrix)) next

    state <- state_matrix[, 1]
    if (length(state) == length(gene_names)) {
      names(state) <- gene_names
    }
    fixed_rows[[length(fixed_rows) + 1]] <- state
  }

  fixed_rows
}

write_fixed_points <- function(attractor_obj, out_path, gene_names) {
  fixed_rows <- extract_fixed_points_rows(attractor_obj, gene_names)

  if (length(fixed_rows) == 0) {
    writeLines("No fixed points found (or could not extract them from BoolNet attractor object).", out_path)
    cat("Wrote:", out_path, "\n")
    return()
  }

  normalized_rows <- lapply(fixed_rows, function(state) {
    values <- as.integer(state)
    if (length(values) != length(gene_names)) {
      return(NULL)
    }
    values
  })
  normalized_rows <- Filter(Negate(is.null), normalized_rows)

  if (length(normalized_rows) == 0) {
    writeLines(
      "Fixed points were detected by BoolNet, but their state vectors could not be exported in tabular form.",
      out_path
    )
    cat("Wrote:", out_path, "\n")
    return()
  }

  mat <- matrix(
    unlist(normalized_rows, use.names = FALSE),
    ncol = length(gene_names),
    byrow = TRUE
  )
  colnames(mat) <- gene_names
  write.table(mat, file = out_path, sep = "\t", row.names = FALSE, col.names = TRUE, quote = FALSE)
  cat("Wrote:", out_path, "\n")
}

main <- function() {
  args <- parse_args(commandArgs(trailingOnly = TRUE))
  if (is.null(args$bnet) || is.null(args$config)) {
    print_usage()
    stop("Both --bnet and --config are required.")
  }

  cfg <- read_kv_config(args$config)

  num_series <- cfg_get_int(cfg, c("num_traces", "num_series"), 15)
  num_measurements <- cfg_get_int(cfg, c("num_steps", "num_measurements"), 8)
  update_type <- cfg_get(cfg, c("update_type"), "synchronous")
  noise_level <- cfg_get_num(cfg, c("noise_level"), 0.0)

  output_dir <- cfg_get(cfg, c("output_dir"), "outputs/traces")
  output_prefix <- cfg_get(cfg, c("output_prefix"), "experiment")
  output_suffix <- cfg_get(cfg, c("output_suffix"), ".txt")
  write_header <- cfg_get_bool(cfg, c("write_trajectory_header"), FALSE)
  write_genes_file <- cfg_get_bool(cfg, c("write_genes_file"), TRUE)

  find_attractors <- cfg_get_bool(cfg, c("find_attractors"), FALSE)
  find_fixed_points <- cfg_get_bool(cfg, c("find_fixed_points"), FALSE)
  attractor_type <- cfg_get(cfg, c("attractor_update_type"), update_type)

  seed_value <- cfg_get_int(cfg, c("seed"), NULL)
  if (!is.null(seed_value)) {
    set.seed(seed_value)
    cat("Using seed:", seed_value, "\n")
  }

  if (num_series <= 0) stop("num_traces/num_series must be >= 1")
  if (num_measurements <= 0) stop("num_steps/num_measurements must be >= 1")
  if (!(tolower(update_type) %in% c("synchronous", "asynchronous"))) {
    stop("update_type must be 'synchronous' or 'asynchronous'")
  }
  if (!(tolower(attractor_type) %in% c("synchronous", "asynchronous"))) {
    stop("attractor_update_type must be 'synchronous' or 'asynchronous'")
  }

  cat("Loading network:", args$bnet, "\n")
  net <- loadNetwork(args$bnet)
  genes <- net$genes

  cat("Network genes (", length(genes), "): ", paste(genes, collapse = ", "), "\n", sep = "")
  cat("Generating traces with settings:\n")
  cat("  num_series       =", num_series, "\n")
  cat("  num_measurements =", num_measurements, "\n")
  cat("  update_type      =", update_type, "\n")
  cat("  noise_level      =", noise_level, "\n")

  ts <- generateTimeSeries(
    net,
    numSeries = num_series,
    numMeasurements = num_measurements,
    type = update_type,
    noiseLevel = noise_level
  )

  for (i in seq_along(ts)) {
    if (is.null(rownames(ts[[i]]))) {
      rownames(ts[[i]]) <- genes
    }
  }

  write_traces(ts, genes, output_dir, output_prefix, output_suffix, write_header)

  if (write_genes_file) {
    ensure_dir(output_dir)
    genes_file <- file.path(output_dir, "genes.txt")
    writeLines(genes, genes_file)
    cat("Wrote:", genes_file, "\n")
  }

  if (find_attractors || find_fixed_points) {
    cat("Computing attractors (type =", attractor_type, ")...\n")
    attrs <- getAttractors(net, type = attractor_type)

    if (find_attractors) {
      attractor_file <- file.path(output_dir, "attractors_summary.txt")
      write_text_dump(attractor_file, attrs, label = "BoolNet attractors")
    }

    if (find_fixed_points) {
      fixed_points_file <- file.path(output_dir, "fixed_points.txt")
      write_fixed_points(attrs, fixed_points_file, genes)
    }
  }

  cat("Done.\n")
}

main()
