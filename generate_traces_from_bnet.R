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

cleanup_trace_outputs <- function(out_dir, prefix, suffix) {
  ensure_dir(out_dir)

  suffix_escaped <- gsub("([][{}()+*^$|\\\\?.])", "\\\\\\1", suffix)
  pattern <- paste0("^", prefix, "[0-9]+", suffix_escaped, "$")
  old_files <- list.files(out_dir, pattern = pattern, full.names = TRUE)

  if (length(old_files) > 0) {
    removed <- file.remove(old_files)
    if (!all(removed)) {
      failed <- old_files[!removed]
      stop(sprintf("Failed to remove stale trace files: %s", paste(failed, collapse = ", ")))
    }
    cat("Removed", length(old_files), "stale trace file(s).\n")
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

  cleanup_trace_outputs(output_dir, output_prefix, output_suffix)
  write_traces(ts, genes, output_dir, output_prefix, output_suffix, write_header)

  if (write_genes_file) {
    ensure_dir(output_dir)
    genes_file <- file.path(output_dir, "genes.txt")
    writeLines(genes, genes_file)
    cat("Wrote:", genes_file, "\n")
  }

  cat("Done.\n")
}

main()
