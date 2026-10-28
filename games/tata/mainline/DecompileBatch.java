// javac -cp PATH/unluac.jar -d .local games/tata/mainline/DecompileBatch.java
// java -cp ".local;PATH/unluac.jar" DecompileBatch INPUT_DIR OUTPUT_DIR
import java.nio.file.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.stream.*;

public class DecompileBatch {
    public static void main(String[] args) throws Exception {
        Path input = Path.of(args[0]).toRealPath();
        Path output = Path.of(args[1]).toAbsolutePath().normalize();
        if (output.startsWith(input)) throw new IllegalArgumentException("Output must be outside input");
        Files.createDirectories(output);
        List<Path> paths;
        try (Stream<Path> stream = Files.walk(input)) {
            paths = stream.filter(p -> p.toString().endsWith(".luae")).sorted().collect(Collectors.toList());
        }
        int success = 0;
        List<String> errors = new ArrayList<>();
        for (Path path : paths) {
            Path relative = input.relativize(path);
            Path target = output.resolve(relative.toString().replaceAll("\\.luae$", ".lua"));
            Files.createDirectories(target.getParent());
            try {
                unluac.Main.decompile(path.toString(), target.toString(), new unluac.Configuration());
                success++;
            } catch (Exception | AssertionError e) {
                Files.deleteIfExists(target);
                errors.add(relative + "\t" + e.toString());
            }
            if ((success + errors.size()) % 250 == 0)
                System.out.println("processed=" + (success + errors.size()) + " success=" + success + " errors=" + errors.size());
        }
        Files.write(output.resolve("decompile-errors.tsv"), errors, StandardCharsets.UTF_8);
        String report = "total=" + paths.size() + " success=" + success + " errors=" + errors.size();
        Files.writeString(output.resolve("decompile-report.txt"), report, StandardCharsets.UTF_8);
        System.out.println(report);
        if (!errors.isEmpty()) System.exit(1);
    }
}
