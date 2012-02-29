desc "Run hg purge & git clean, but exclude secrets and other dev env files"
task :clean do
    exclude_patterns = %w[
        secrets*.py
        .tags*
        deploy/node_modules
    ]
    args = exclude_patterns.map {|s| "-X \"#{s}\""}.join(" ")
    system "hg purge --all #{args}"
    Dir.chdir "khan-exercises" do
        system "git", "clean", "-Xdf"
    end
end

desc "Compile handlebars templates"
task :handlebars do
    system "python", "deploy/compile_handlebar_templates.py"
end

desc "Compile jinja templates"
task :jinja do
    system "python", "deploy/compile_templates.py"
end

desc "Pack exercise files"
task :exercises do
    system "ruby", "khan-exercises/build/pack.rb"
end

desc "Compress javascript"
task :js do
    system "python", "deploy/compress.py", "js"
end

desc "Compress css"
task :css do
    system "python", "deploy/compress.py", "css"
end
